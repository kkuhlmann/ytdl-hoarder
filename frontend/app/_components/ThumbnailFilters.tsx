/**
 * Hidden SVG filter defs for thumbnail effects. Mounted once in the root layout
 * so `filter: url(#thumb-edge)` resolves globally.
 *
 * #thumb-edge: grayscale → Laplacian edge detection (bright edges on black) →
 * soft glow. Used by "wire" thumbnail mode; the accent-colored `.thumb-tint`
 * overlay (mix-blend multiply) recolors the white edges to the active theme.
 */
export function ThumbnailFilters() {
  return (
    <svg
      width="0"
      height="0"
      aria-hidden
      focusable="false"
      style={{ position: "absolute" }}
    >
      <filter
        id="thumb-edge"
        x="0"
        y="0"
        width="100%"
        height="100%"
        colorInterpolationFilters="sRGB"
      >
        <feColorMatrix type="saturate" values="0" result="gray" />
        <feConvolveMatrix
          in="gray"
          order="3"
          preserveAlpha="true"
          kernelMatrix="1 1 1  1 -8 1  1 1 1"
          result="rawEdges"
        />
        {/* Brighten: push faint edges toward white so they reach full accent
            through the multiply blend, giving a brighter wireframe. */}
        <feComponentTransfer in="rawEdges" result="edges">
          <feFuncR type="linear" slope="4.5" intercept="0.12" />
          <feFuncG type="linear" slope="4.5" intercept="0.12" />
          <feFuncB type="linear" slope="4.5" intercept="0.12" />
        </feComponentTransfer>
        <feGaussianBlur in="edges" stdDeviation="1.4" result="glow" />
        <feMerge>
          <feMergeNode in="glow" />
          <feMergeNode in="glow" />
          <feMergeNode in="edges" />
          <feMergeNode in="edges" />
        </feMerge>
      </filter>
    </svg>
  )
}
