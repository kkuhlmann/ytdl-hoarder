"use client"

import type { Dispatch, SetStateAction } from "react"
import { GroupFolderCard } from "./GroupFolderCard"
import { GroupBreadcrumb } from "./GroupBreadcrumb"
import { CardGrid } from "./data/CardGrid"
import { TablePagination } from "./TablePagination"
import type { MediaGroup } from "@/app/types/DownloadsOptions"

type Props = {
  breadcrumb: { dimLabel: string; segments: { key: string; label: string }[] }
  folders: MediaGroup[]
  loading: boolean
  pageCount: number
  pageNumber: number
  setPageNumber: Dispatch<SetStateAction<number>>
  canGoUp: boolean
  onGoUp: () => void
  onOpen: (group: MediaGroup) => void
}

export function GroupFolderGrid({
  breadcrumb,
  folders,
  loading,
  pageCount,
  pageNumber,
  setPageNumber,
  canGoUp,
  onGoUp,
  onOpen,
}: Props) {
  return (
    <div>
      <GroupBreadcrumb breadcrumb={breadcrumb} canGoUp={canGoUp} onGoUp={onGoUp} />

      <CardGrid
        rows={folders}
        loading={loading}
        emptyMessage="No groups found"
        getRowKey={(group) => group.key}
        renderCard={(group, index) => (
          <GroupFolderCard
            group={group}
            index={index}
            onClick={() => onOpen(group)}
          />
        )}
      />

      {pageCount > 1 && (
        <TablePagination
          pageNumber={pageNumber}
          pageCount={pageCount}
          setPageNumber={setPageNumber}
        />
      )}
    </div>
  )
}
