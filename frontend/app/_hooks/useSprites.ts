import { useState } from 'react'
import axios from 'axios'
import { apiUrl } from '@/app/lib/api'
import { mediaApi } from '@/app/lib/mediaApi'
import { useFetchEffect } from '@/app/_hooks/useFetchEffect'

interface SpriteMetadata {
  width: number
  height: number
  columns: number
  rows: number
  interval: number
  total_frames: number
}

interface UseSpritesOptions {
  mediaDetailsId: number
  enabled?: boolean
}

interface UseSpritesResult {
  metadata: SpriteMetadata | null
  spriteUrl: string
  available: boolean
  isLoading: boolean
}

export function useSprites({
  mediaDetailsId,
  enabled = true,
}: UseSpritesOptions): UseSpritesResult {
  const [metadata, setMetadata] = useState<SpriteMetadata | null>(null)
  const [available, setAvailable] = useState(false)

  const spriteUrl = apiUrl(mediaApi.sprites(mediaDetailsId))

  const { isLoading } = useFetchEffect(
    (signal) => {
      setAvailable(false)
      setMetadata(null)
      return axios
        .get<SpriteMetadata>(apiUrl(mediaApi.spriteMetadata(mediaDetailsId)), { signal })
        .then((response) => {
          setMetadata(response.data)
          setAvailable(true)

          const img = new Image()
          img.src = spriteUrl
        })
        .catch((err) => {
          if (axios.isCancel(err)) return
          // 404 = sprites not generated yet — not an error, just unavailable
          setAvailable(false)
        })
    },
    [mediaDetailsId, spriteUrl],
    { enabled }
  )

  return { metadata, spriteUrl, available, isLoading }
}
