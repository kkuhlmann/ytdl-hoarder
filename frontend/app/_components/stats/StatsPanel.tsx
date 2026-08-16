"use client"

import { motion, useReducedMotion } from "framer-motion"
import type { ReactNode } from "react"

interface StatsPanelProps {
  id: string
  title: string
  children: ReactNode
}

// A single section panel: bordered surface card + anchor id (quick-nav target) +
// subtle entrance motion + hover polish. Centralizes the visual treatment so
// sections stay focused on their content.
export function StatsPanel({ id, title, children }: StatsPanelProps) {
  const reduce = useReducedMotion()
  return (
    <motion.section
      id={id}
      className="scroll-mt-28 rounded-lg border border-border bg-bg-surface p-4 sm:p-5 transition-colors hover:border-matrix/40"
      initial={reduce ? false : { opacity: 0, y: 8 }}
      whileInView={reduce ? undefined : { opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-10%" }}
      transition={{ duration: 0.25 }}
    >
      <div className="flex items-center justify-between gap-3 mb-4 border-b border-border pb-2">
        <h2 className="text-lg font-mono font-semibold text-text-primary">{title}</h2>
      </div>
      {children}
    </motion.section>
  )
}
