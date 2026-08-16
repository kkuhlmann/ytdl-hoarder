"use client"

import { useEffect, useState } from "react"

export interface NavSection {
  id: string
  label: string
}

// Quick-nav chips that jump to section panels, with an IntersectionObserver
// scroll-spy that highlights the section currently in view.
export function StatsSectionNav({ sections }: { sections: NavSection[] }) {
  const [active, setActive] = useState<string | null>(sections[0]?.id ?? null)

  useEffect(() => {
    const els = sections
      .map((s) => document.getElementById(s.id))
      .filter((el): el is HTMLElement => el !== null)
    if (els.length === 0) return
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting)
        if (visible.length > 0) {
          setActive(
            visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0].target.id,
          )
        }
      },
      { rootMargin: "-120px 0px -70% 0px", threshold: 0 },
    )
    els.forEach((el) => obs.observe(el))
    return () => obs.disconnect()
  }, [sections])

  return (
    <nav className="flex gap-1 overflow-x-auto scrollbar-none [&::-webkit-scrollbar]:hidden">
      {sections.map((s) => (
        <a
          key={s.id}
          href={`#${s.id}`}
          onClick={(e) => {
            e.preventDefault()
            document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth" })
          }}
          className={`shrink-0 px-2.5 py-1 text-xs font-mono rounded transition-colors ${
            active === s.id
              ? "bg-matrix/20 text-matrix"
              : "text-text-muted hover:text-text-secondary hover:bg-bg-elevated"
          }`}
        >
          {s.label}
        </a>
      ))}
    </nav>
  )
}
