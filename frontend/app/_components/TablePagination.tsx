"use client"

import { Button } from "@/components/ui/button"
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronDoubleLeftIcon,
  ChevronDoubleRightIcon,
} from "@heroicons/react/20/solid"
type TablePaginationProps = {
  pageNumber: number
  setPageNumber: (page: number) => void
  pageCount: number
}

export function TablePagination({
  pageNumber,
  setPageNumber,
  pageCount,
}: TablePaginationProps) {
  return (
    <div className="flex items-center justify-center gap-2 py-4 px-2">
      <Button
        variant="outline"
        size="sm"
        disabled={pageNumber === 1}
        onClick={() => setPageNumber(1)}
        title="First page"
      >
        <ChevronDoubleLeftIcon className="h-4 w-4" />
      </Button>

      <Button
        variant="outline"
        size="sm"
        disabled={pageNumber === 1}
        onClick={() => setPageNumber(pageNumber - 1)}
        className="gap-1"
      >
        <ChevronLeftIcon className="h-4 w-4" />
        <span className="hidden sm:inline">Previous</span>
      </Button>

      <div className="flex items-center gap-2 px-4">
        <span className="font-mono text-sm text-text-secondary">
          Page{" "}
          <span className="text-matrix font-semibold">{pageNumber}</span>
          {" / "}
          <span className="text-text-primary">{pageCount === 0 ? "?" : pageCount}</span>
        </span>
      </div>

      <Button
        variant="outline"
        size="sm"
        disabled={pageNumber === pageCount || pageCount === 0}
        onClick={() => setPageNumber(pageNumber + 1)}
        className="gap-1"
      >
        <span className="hidden sm:inline">Next</span>
        <ChevronRightIcon className="h-4 w-4" />
      </Button>

      <Button
        variant="outline"
        size="sm"
        disabled={pageNumber === pageCount || pageCount === 0}
        onClick={() => setPageNumber(pageCount)}
        title="Last page"
      >
        <ChevronDoubleRightIcon className="h-4 w-4" />
      </Button>
    </div>
  )
}
