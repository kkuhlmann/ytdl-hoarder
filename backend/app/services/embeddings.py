import json

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

from logger import logger

SUPPORTED_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
ONNX_WEIGHTS = 'onnx/model.onnx'
BATCH_SIZE = 32


def _load_json(repo: str, filename: str) -> dict:
    with open(hf_hub_download(repo, filename), encoding='utf-8') as f:
        return json.load(f)


def resolve_model_repo(name: str) -> str:
    """Expand a configured embedding model name to its full Hub repo id.

    Raises ValueError for anything other than the supported model.
    """
    repo = name if '/' in name else f'sentence-transformers/{name}'
    if repo != SUPPORTED_MODEL:
        msg = (
            f'Unsupported embedding model {name!r} (resolved to {repo!r}). '
            f'Only {SUPPORTED_MODEL!r} is supported. Embeddings are not comparable '
            'across models, so switching would invalidate every stored vector.'
        )
        raise ValueError(msg)
    return repo


class OnnxEmbedder:
    """Sentence embedding encoder backed by onnxruntime.

    Reproduces the sentence-transformers pipeline for the supported model —
    transformer, attention-masked mean pooling, L2 normalize — so that vectors
    stay interchangeable with those already stored in transcript_embeddings.

    Weights and tokenizer are fetched from the Hub on first use and cached under
    HF_HOME.
    """

    def __init__(self, model_name: str):
        repo = resolve_model_repo(model_name)

        pooling = _load_json(repo, '1_Pooling/config.json')
        if not pooling.get('pooling_mode_mean_tokens'):
            msg = f'{repo!r} does not use mean pooling; this encoder implements mean pooling only.'
            raise ValueError(msg)
        self.dimension = pooling['word_embedding_dimension']

        # max_seq_length belongs to the sentence-transformers config, not the
        # tokenizer, which reports the architecture's 512-token limit instead.
        # Truncating at the wrong length yields embeddings that silently drift
        # from the stored ones rather than failing.
        max_length = _load_json(repo, 'sentence_bert_config.json')['max_seq_length']

        tokenizer = Tokenizer.from_file(hf_hub_download(repo, 'tokenizer.json'))
        tokenizer.enable_truncation(max_length=max_length)
        # S106: `pad_token` is the tokenizer's padding symbol, not a credential.
        tokenizer.enable_padding(pad_id=tokenizer.token_to_id('[PAD]'), pad_token='[PAD]')  # noqa: S106
        self._tokenizer = tokenizer

        session_options = ort.SessionOptions()
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            hf_hub_download(repo, ONNX_WEIGHTS),
            session_options,
            providers=['CPUExecutionProvider'],
        )
        self._input_names = {i.name for i in self._session.get_inputs()}

        logger.info(f'Loaded ONNX embedding model {repo} ({self.dimension}d, max {max_length} tok)')

    def encode(self, sentences: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        """Encode sentences into a (len(sentences), dimension) float32 array."""
        if isinstance(sentences, str):
            msg = 'encode() takes a list of strings, not a single string'
            raise TypeError(msg)
        if not sentences:
            return np.empty((0, self.dimension), dtype=np.float32)

        batches = [
            self._encode_batch(sentences[i : i + BATCH_SIZE])
            for i in range(0, len(sentences), BATCH_SIZE)
        ]
        embeddings = np.concatenate(batches).astype(np.float32)

        if normalize_embeddings:
            embeddings /= np.clip(np.linalg.norm(embeddings, axis=1, keepdims=True), 1e-12, None)
        return embeddings

    def _encode_batch(self, batch: list[str]) -> np.ndarray:
        encodings = self._tokenizer.encode_batch(batch)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feed = {
            'input_ids': np.array([e.ids for e in encodings], dtype=np.int64),
            'attention_mask': attention_mask,
            'token_type_ids': np.array([e.type_ids for e in encodings], dtype=np.int64),
        }

        # Exports vary in which inputs they declare; feeding an undeclared one
        # raises rather than being ignored.
        feed = {name: value for name, value in feed.items() if name in self._input_names}
        hidden_state = self._session.run(None, feed)[0]

        weights = attention_mask[..., None].astype(np.float32)
        return (hidden_state * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
