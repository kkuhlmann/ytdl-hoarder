"use client"

import React from "react"

import { ActionMenu } from "@/app/_components/data/ActionMenu"

/**
 * Card action icons, in the two forms a card needs.
 *
 * Extracted from DownloadsGrid so playlist cards reuse it rather than becoming
 * a third copy. The comments below are the only record of why this structure
 * exists — keep them with the code.
 */
export function CardActionOverlay({ actions }: { actions: React.ReactNode }) {
  return (
    <>
      {/* Actions, pointer devices only: six icons are wider than a card, so
          rather than costing a body row they overlay the thumbnail and fade in
          on hover. Touch devices get the ⋯ menu below instead — they have no
          hover, and a permanent strip would cover a third of the poster.
          Gated on hover capability rather than width so tablets (4 columns at
          768px, no hover) get the tappable copy, not the hover one.
          The icons sit on their own solid pill rather than a gradient scrim:
          a gradient can't guarantee contrast over an arbitrary thumbnail, and
          a theme surface keeps every icon's own semantic color (transcript
          status especially) legible across all ~40 themes, light ones too. */}
      <div
        className="absolute inset-x-0 bottom-0 hidden [@media(hover:hover)]:flex justify-center px-2 pb-2 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-0.5 rounded-md border border-border bg-bg-elevated/95 px-1 py-0.5 shadow-lg backdrop-blur-xs [&_svg]:h-3.5 [&_svg]:w-3.5">
          {actions}
        </div>
      </div>

      {/* Actions, touch devices only: one chip that opens the same icons in a
          popover, so the card body carries no action row at all. */}
      <ActionMenu
        actions={actions}
        className="absolute bottom-1.5 right-1.5 [@media(hover:hover)]:hidden rounded bg-black/75 p-1.5 leading-none text-white"
      />
    </>
  )
}
