"use client"

import { motion } from "framer-motion"

function Loading() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-8">
      <div className="relative">
        <motion.div
          className="h-8 w-8 rounded-full border-2 border-matrix/30"
          animate={{ rotate: 360 }}
          transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
        />
        <motion.div
          className="absolute top-0 left-0 h-8 w-8 rounded-full border-2 border-transparent border-t-matrix"
          style={{ boxShadow: "0 0 10px var(--matrix-glow)" }}
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
        />
      </div>
      <span className="font-mono text-sm text-matrix animate-pulse">
        Loading<span className="animate-blink">_</span>
      </span>
    </div>
  )
}

export function LoadingTable({ length }: { length: number }) {
  return (
    <tr>
      <td colSpan={length} className="p-0">
        <Loading />
      </td>
    </tr>
  )
}

export function LoadingSpinner() {
  return (
    <motion.div
      className="h-4 w-4 rounded-full border-2 border-transparent border-t-current"
      animate={{ rotate: 360 }}
      transition={{ duration: 0.8, repeat: Infinity, ease: "linear" }}
    />
  )
}
