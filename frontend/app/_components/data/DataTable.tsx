"use client"

import React, { useRef, useState } from "react"
import { motion } from "framer-motion"
import { ChevronUpIcon, ChevronDownIcon } from "@heroicons/react/20/solid"
import { DndContext, DragOverlay, closestCenter } from "@dnd-kit/core"
import type { DragEndEvent, DragStartEvent } from "@dnd-kit/core"
import { restrictToVerticalAxis } from "@dnd-kit/modifiers"
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"

import { cn } from "@/lib/utils"
import { Checkbox } from "@/components/ui/checkbox"
import { Separator } from "@/components/ui/separator"
import { LoadingSpinner, LoadingTable } from "@/app/_components/LoadingSpinner"
import { SortChips } from "@/app/_components/SortChips"
import { ActionMenu } from "@/app/_components/data/ActionMenu"
import { useRowDragSensors } from "@/app/_components/data/dndSensors"
import { useDelayedFlag } from "@/app/_hooks/useDelayedFlag"
import type { SortDirection } from "@/app/types/DownloadsOptions"

export type Breakpoint = "always" | "sm" | "md" | "lg" | "xl"

/**
 * Column visibility per breakpoint. Applied to the <th> and the <td> from the
 * same descriptor, which is the whole point: the previous scheme keyed these to
 * array position (`idx === 2 && "hidden md:table-cell"`) while the cells were
 * hand-written in a fixed order, so inserting a column silently desynchronised
 * headers from data.
 */
export const BREAKPOINT_CLASS: Record<Breakpoint, string> = {
  always: "",
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
  xl: "hidden xl:table-cell",
}

/**
 * Where a column appears in the mobile card, which is composed from these same
 * `render` functions rather than a second hand-written markup tree.
 *
 *  leading — before the title (a position number)
 *  title   — the primary line
 *  badge   — inline next to the title
 *  meta    — joined by "·" on the second line
 *  hidden  — desktop only (the default)
 */
export type MobileRole = "leading" | "title" | "badge" | "meta" | "hidden"

export type Column<T> = {
  /** Stable id; also the sort key when `sortable`. */
  key: string
  label: React.ReactNode
  sortable?: boolean
  breakpoint?: Breakpoint
  render: (row: T) => React.ReactNode
  /**
   * Mobile form of the same value. The desktop cell carries table chrome
   * (truncation, `block`, its own font size) that fights the card's compact
   * layout, so a column whose mobile presentation differs supplies the bare
   * value here. Defaults to `render`.
   */
  renderMobile?: (row: T) => React.ReactNode
  thClassName?: string
  /** Width caps and cell padding overrides live here, per column. */
  tdClassName?: string
  /** Stop a click in this cell from triggering the row's onClick. */
  stopRowClick?: boolean
  mobile?: MobileRole
  /**
   * Order within its mobile role, when it differs from column order. Lower
   * first; unset sorts last. Media puts duration ahead of channel on the meta
   * line because it's short and fixed-width, so the channel absorbs the
   * truncation rather than the duration being what gets cut off.
   */
  mobileOrder?: number
}

export type DataTableSelection<T> = {
  selectedIds: Set<number>
  onSelectionChange: (ids: Set<number>) => void
  allSelected: boolean
  onSelectAll: (selected: boolean) => void
  idOf: (row: T) => number
}

export type DataTableDragAndDrop<T> = {
  /** Indices into `rows`. Both renderings report the same thing. */
  onReorder: (fromIndex: number, toIndex: number) => void
  /**
   * Makes dragging inert without unmounting the DndContext. Surfaces that only
   * allow reordering under one sort order flip this rather than dropping the
   * prop, which would remount the whole list on every sort change.
   */
  disabled?: boolean
  /** Contents of the lifted clone. The table supplies the DragOverlay itself. */
  renderOverlay?: (row: T) => React.ReactNode
}

/**
 * The current row's drag bindings, for a cell that wants to draw a handle.
 *
 * The listeners have to reach a `Column.render(row)` function, which by design
 * receives only the row. A context is the seam that reaches it without widening
 * `Column<T>` for every surface that will never drag anything.
 */
export type RowDragState = {
  attributes: ReturnType<typeof useSortable>["attributes"]
  listeners: ReturnType<typeof useSortable>["listeners"]
  isDragging: boolean
  disabled: boolean
}

const RowDragContext = React.createContext<RowDragState | null>(null)

/** Null outside a draggable row — i.e. on every surface that isn't reorderable. */
export const useRowDrag = () => React.useContext(RowDragContext)

type SortableRowProps = {
  id: string
  disabled: boolean
  children: React.ReactNode
  className?: string
  style?: React.CSSProperties
  onClick?: () => void
}

function useSortableRow(id: string, disabled: boolean) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id, disabled })

  // The row carries the pointer activators; the drag handle inside it carries
  // onKeyDown. Spreading onKeyDown here too would activate the keyboard sensor
  // twice, since a keydown on the handle bubbles up to the row.
  const { onKeyDown: _keyboard, ...pointerListeners } = listeners ?? {}

  const dragState = React.useMemo<RowDragState>(
    () => ({ attributes, listeners, isDragging, disabled }),
    [attributes, listeners, isDragging, disabled],
  )

  return {
    setNodeRef,
    dragState,
    pointerListeners,
    className: cn(!disabled && "cursor-grab", isDragging && "opacity-40"),
    // Spread *after* the caller's style so a row gradient survives, but the
    // drag transform still wins.
    dragStyle: {
      transform: CSS.Transform.toString(transform),
      transition,
    } as React.CSSProperties,
  }
}

function SortableTableRow({
  id,
  disabled,
  children,
  className,
  style,
  onClick,
}: SortableRowProps) {
  // Destructured rather than kept as one `row` object: passing an object
  // *property* to `ref=` makes the compiler treat the whole object as a ref, so
  // every other property read here would be a render-phase ref access.
  const { setNodeRef, dragState, pointerListeners, className: rowClassName, dragStyle } =
    useSortableRow(id, disabled)
  return (
    <tr
      ref={setNodeRef}
      {...pointerListeners}
      onClick={onClick}
      className={cn(className, rowClassName)}
      style={{ ...style, ...dragStyle }}
    >
      {/* A Provider emits no DOM, so this is still a valid <tr> of <td>s. */}
      <RowDragContext.Provider value={dragState}>
        {children}
      </RowDragContext.Provider>
    </tr>
  )
}

function SortableMobileRow({
  id,
  disabled,
  children,
  className,
  style,
  onClick,
}: SortableRowProps) {
  // Destructured for the same reason as SortableTableRow above.
  const { setNodeRef, dragState, pointerListeners, className: rowClassName, dragStyle } =
    useSortableRow(id, disabled)
  return (
    <div
      ref={setNodeRef}
      {...pointerListeners}
      onClick={onClick}
      className={cn(className, rowClassName)}
      style={{ ...style, ...dragStyle }}
    >
      <RowDragContext.Provider value={dragState}>
        {children}
      </RowDragContext.Provider>
    </div>
  )
}

/**
 * One rendering's worth of drag wiring.
 *
 * Called once per tree, because DataTable renders the mobile list and the
 * desktop table simultaneously and hides one with CSS. A single DndContext
 * would register every row id twice, and a single active-row state would light
 * up the hidden tree's overlay alongside the visible one's.
 */
function useTreeDrag<T>(
  rows: T[],
  dndIds: string[],
  dragAndDrop: DataTableDragAndDrop<T> | undefined,
  suppressClickRef: React.MutableRefObject<boolean>,
) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const sensors = useRowDragSensors()

  const activeIndex = activeId === null ? -1 : dndIds.indexOf(activeId)
  const activeRow = activeIndex >= 0 ? rows[activeIndex] : undefined

  const onDragStart = (event: DragStartEvent) =>
    setActiveId(String(event.active.id))

  const onDragCancel = () => setActiveId(null)

  const onDragEnd = (event: DragEndEvent) => {
    setActiveId(null)
    // The pointer-up that ends a drag also arrives as a click on whatever was
    // dropped onto, which on these surfaces means starting playback.
    suppressClickRef.current = true
    window.setTimeout(() => {
      suppressClickRef.current = false
    }, 0)

    const { active, over } = event
    if (!over || active.id === over.id) return
    const from = dndIds.indexOf(String(active.id))
    const to = dndIds.indexOf(String(over.id))
    if (from >= 0 && to >= 0) dragAndDrop?.onReorder(from, to)
  }

  return { sensors, activeRow, onDragStart, onDragCancel, onDragEnd }
}

export type DataTableProps<T> = {
  columns: Column<T>[]
  rows: T[]
  loading: boolean
  emptyMessage: string
  getRowKey: (row: T) => React.Key
  onRowClick?: (row: T) => void
  rowClassName?: (row: T) => string | undefined
  rowStyle?: (row: T) => React.CSSProperties | undefined
  /** Omit all three for a list that doesn't sort (headers become inert). */
  sortBy?: string | null
  sortDirection?: SortDirection
  onSort?: (column: string) => void
  sortOptions?: { key: string; label: string }[]
  /** Row action icons, as a fragment. The table supplies the container. */
  renderActions?: (row: T) => React.ReactNode
  /** Secondary line on the mobile card (e.g. the currently-sorted timestamp). */
  mobileMeta?: (row: T) => React.ReactNode
  /** Full override of the mobile card, for rows the role model doesn't fit. */
  mobileRow?: (row: T, index: number) => React.ReactNode
  selection?: DataTableSelection<T>
  /**
   * Makes rows draggable in both renderings. Omit for a list that doesn't
   * reorder — the row then keeps its entrance animation, which drag rows have
   * to give up (framer and dnd-kit would both be writing `transform`).
   */
  dragAndDrop?: DataTableDragAndDrop<T>
}

const cellPadding = "py-1 px-2 md:py-1.5 md:px-3"

function SortArrow({
  column,
  sortBy,
  sortDirection,
}: {
  column: string
  sortBy: string | null
  sortDirection: SortDirection
}) {
  if (sortBy !== column) return null
  return sortDirection === "asc" ? (
    <ChevronUpIcon className="h-4 w-4 inline ml-1" />
  ) : (
    <ChevronDownIcon className="h-4 w-4 inline ml-1" />
  )
}

/**
 * Responsive list: a sortable table on sm and up, stacked cards below it.
 *
 * Both renderings are driven by one column descriptor list, so a surface adds a
 * column by describing it rather than by editing markup in two places.
 */
export function DataTable<T>({
  columns,
  rows,
  loading,
  emptyMessage,
  getRowKey,
  onRowClick,
  rowClassName,
  rowStyle,
  sortBy = null,
  sortDirection = null,
  onSort,
  sortOptions,
  renderActions,
  mobileMeta,
  mobileRow,
  selection,
  dragAndDrop,
}: DataTableProps<T>) {
  // Spinner only after 500ms, so a fast refetch doesn't flash one.
  const delayedLoading = useDelayedFlag(loading)

  // dnd-kit ids are string | number; React.Key also admits bigint.
  const dndIds = rows.map((row) => String(getRowKey(row)))
  const suppressClickRef = useRef(false)
  const mobileDrag = useTreeDrag(rows, dndIds, dragAndDrop, suppressClickRef)
  const desktopDrag = useTreeDrag(rows, dndIds, dragAndDrop, suppressClickRef)

  const handleRowClick = (row: T) => {
    if (suppressClickRef.current) return
    onRowClick?.(row)
  }

  /**
   * Wraps one rendering in its own drag context. A plain function rather than a
   * component: an inline component's identity changes every render, which would
   * remount the whole tree underneath it on each keystroke.
   */
  const withDnd = (
    tree: React.ReactNode,
    drag: ReturnType<typeof useTreeDrag<T>>,
  ) =>
    dragAndDrop ? (
      <DndContext
        sensors={drag.sensors}
        collisionDetection={closestCenter}
        modifiers={[restrictToVerticalAxis]}
        onDragStart={drag.onDragStart}
        onDragCancel={drag.onDragCancel}
        onDragEnd={drag.onDragEnd}
      >
        <SortableContext items={dndIds} strategy={verticalListSortingStrategy}>
          {tree}
        </SortableContext>
        <DragOverlay dropAnimation={{ duration: 180, easing: "ease-out" }}>
          {drag.activeRow && dragAndDrop.renderOverlay
            ? dragAndDrop.renderOverlay(drag.activeRow)
            : null}
        </DragOverlay>
      </DndContext>
    ) : (
      tree
    )

  const isSelected = (row: T) =>
    selection ? selection.selectedIds.has(selection.idOf(row)) : false

  const toggleRow = (row: T, checked: boolean) => {
    if (!selection) return
    const next = new Set(selection.selectedIds)
    if (checked) next.add(selection.idOf(row))
    else next.delete(selection.idOf(row))
    selection.onSelectionChange(next)
  }

  const columnCount = columns.length + (selection ? 1 : 0)

  const byRole = (role: MobileRole) =>
    columns
      .filter((c) => c.mobile === role)
      .sort(
        (a, b) =>
          (a.mobileOrder ?? Number.MAX_SAFE_INTEGER) -
          (b.mobileOrder ?? Number.MAX_SAFE_INTEGER),
      )
  const leadingCols = byRole("leading")
  const titleCols = byRole("title")
  const badgeCols = byRole("badge")
  const metaCols = byRole("meta")

  const selectAllCheckbox = selection ? (
    <Checkbox
      checked={selection.allSelected && rows.length > 0}
      onCheckedChange={(checked) => selection.onSelectAll(checked === true)}
      disabled={rows.length === 0}
    />
  ) : null

  const defaultMobileRow = (row: T, index: number) => {
    const renderFor = (c: Column<T>) => (c.renderMobile ?? c.render)(row)

    const meta = metaCols
      .map(renderFor)
      .filter((node) => node !== null && node !== undefined && node !== "")

    const className = cn(
      "px-2 py-2 transition-colors active:bg-bg-surface/60",
      // touch-manipulation, not touch-action:none — the latter would stop the
      // list scrolling entirely. With a delay constraint the browser keeps
      // handling pans until the press is held long enough to lift. The
      // selection suppressors keep iOS from raising its text magnifier and
      // callout menu during that hold.
      dragAndDrop && "touch-manipulation select-none [-webkit-touch-callout:none]",
      isSelected(row) && "bg-matrix/5",
      rowClassName?.(row),
    )

    const body = (
      <div className="flex items-start gap-2">
          {selection && (
            <span data-no-dnd="true" className="mt-0.5 shrink-0">
              <Checkbox
                checked={isSelected(row)}
                onCheckedChange={(checked) => toggleRow(row, checked === true)}
                onClick={(e) => e.stopPropagation()}
              />
            </span>
          )}
          {leadingCols.map((c) => (
            <span key={c.key} className="shrink-0">
              {renderFor(c)}
            </span>
          ))}
          <div className="min-w-0 flex-1 flex flex-col gap-1">
            <div className="flex items-baseline gap-2">
              <span className="min-w-0 flex-1 truncate text-sm text-text-primary leading-snug">
                {titleCols.map((c) => (
                  <React.Fragment key={c.key}>{renderFor(c)}</React.Fragment>
                ))}
              </span>
              {mobileMeta && (
                <span className="shrink-0 text-[11px] font-mono text-text-muted">
                  {mobileMeta(row)}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {badgeCols.map((c) => (
                <React.Fragment key={c.key}>{renderFor(c)}</React.Fragment>
              ))}
              <span className="min-w-0 truncate text-[11px] font-mono text-text-muted">
                {meta.map((node, i) => (
                  <React.Fragment key={i}>
                    {i > 0 && " · "}
                    {node}
                  </React.Fragment>
                ))}
              </span>
              {renderActions && (
                <div
                  // -mr-1 pulls the chip flush with the meta line's right edge
                  className="ml-auto -mr-1 shrink-0"
                  data-no-dnd="true"
                  onClick={(e) => e.stopPropagation()}
                >
                  {/* Behind a ⋯ rather than inline: these strips run to nine
                      icons, which at phone width left the channel and duration
                      truncated to nothing. Same menu the grid's cards use on
                      touch, so the two surfaces behave alike. */}
                  <ActionMenu
                    actions={renderActions(row)}
                    className="rounded p-1 text-text-muted transition-colors hover:bg-bg-surface hover:text-text-secondary"
                  />
                </div>
              )}
            </div>
          </div>
      </div>
    )

    if (dragAndDrop) {
      return (
        <SortableMobileRow
          key={getRowKey(row)}
          id={dndIds[index]}
          disabled={dragAndDrop.disabled ?? false}
          className={className}
          style={rowStyle?.(row)}
          onClick={() => handleRowClick(row)}
        >
          {body}
        </SortableMobileRow>
      )
    }

    return (
      <motion.div
        key={getRowKey(row)}
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2, delay: index * 0.02 }}
        onClick={() => handleRowClick(row)}
        className={className}
        style={rowStyle?.(row)}
      >
        {body}
      </motion.div>
    )
  }

  return (
    <>
      {/* Mobile: stacked list. The table's column headers — the only sort
          affordance on desktop — are unusable at this width, so sorting moves
          into the chip strip and each row carries the sorted field inline. */}
      <div className="sm:hidden">
        {(selection || onSort) && (
          <div className="flex items-center gap-2 px-2 pt-2 pb-1.5">
            {selection && (
              <>
                {selectAllCheckbox}
                {onSort && <Separator orientation="vertical" className="h-4" />}
              </>
            )}
            {onSort && (
              <SortChips
                sortBy={sortBy}
                sortDirection={sortDirection}
                onSort={onSort}
                options={sortOptions}
                className="min-w-0 flex-1"
              />
            )}
          </div>
        )}

        {delayedLoading ? (
          <div className="flex justify-center py-10">
            <LoadingSpinner />
          </div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-text-muted font-mono">
            {emptyMessage}
          </div>
        ) : (
          withDnd(
            <div className="border-t border-border divide-y divide-border/50">
              {rows.map((row, index) =>
                mobileRow
                  ? mobileRow(row, index)
                  : defaultMobileRow(row, index),
              )}
            </div>,
            mobileDrag,
          )
        )}
      </div>

      {/* Desktop: full table with sortable column headers.
          overflow-x-auto is containment, not the layout strategy — breakpoints
          keep the table within its container, and this guarantees that a wide
          column can never make the page body itself scroll sideways.

          The drag context wraps this div rather than the <tbody>: DndContext
          renders its own screen-reader live regions inline, and a <div> between
          <table> and <tbody> is invalid markup that the browser hoists out.
          SortableContext, which does sit inside, renders no DOM at all. */}
      {withDnd(
      <div className="hidden sm:block overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-border bg-bg-surface">
              {columns.map((column) => (
                <th
                  key={column.key}
                  className={cn(
                    `${cellPadding} font-mono text-xs text-text-secondary uppercase tracking-wider`,
                    column.sortable &&
                      onSort &&
                      "cursor-pointer hover:text-matrix transition-colors",
                    BREAKPOINT_CLASS[column.breakpoint ?? "always"],
                    column.thClassName,
                  )}
                  onClick={() => column.sortable && onSort?.(column.key)}
                >
                  <span className="flex items-center gap-1">
                    {column.label}
                    {column.sortable && onSort && (
                      <SortArrow
                        column={column.key}
                        sortBy={sortBy}
                        sortDirection={sortDirection}
                      />
                    )}
                  </span>
                </th>
              ))}
              {selection && (
                <th className={`${cellPadding} text-center`}>
                  {selectAllCheckbox}
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {delayedLoading ? (
              <LoadingTable length={columnCount} />
            ) : rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columnCount}
                  className="p-8 text-center text-text-muted font-mono"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              rows.map((row, index) => {
                const cells = (
                  <>
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={cn(
                          cellPadding,
                          BREAKPOINT_CLASS[column.breakpoint ?? "always"],
                          column.tdClassName,
                        )}
                        // The cells that must not start playback are exactly
                        // the cells that must not start a drag.
                        data-no-dnd={column.stopRowClick ? "true" : undefined}
                        onClick={
                          column.stopRowClick
                            ? (e) => e.stopPropagation()
                            : undefined
                        }
                      >
                        {column.render(row)}
                      </td>
                    ))}
                    {selection && (
                      <td
                        className={`${cellPadding} text-center`}
                        data-no-dnd="true"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Checkbox
                          checked={isSelected(row)}
                          onCheckedChange={(checked) =>
                            toggleRow(row, checked === true)
                          }
                        />
                      </td>
                    )}
                  </>
                )

                const className = cn(
                  "group transition-colors duration-200 hover:bg-bg-surface/50",
                  onRowClick && "cursor-pointer",
                  isSelected(row) && "bg-matrix/5",
                  rowClassName?.(row),
                )

                if (dragAndDrop) {
                  return (
                    <SortableTableRow
                      key={getRowKey(row)}
                      id={dndIds[index]}
                      disabled={dragAndDrop.disabled ?? false}
                      className={className}
                      style={rowStyle?.(row)}
                      onClick={() => handleRowClick(row)}
                    >
                      {cells}
                    </SortableTableRow>
                  )
                }

                return (
                  <motion.tr
                    key={getRowKey(row)}
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.2, delay: index * 0.02 }}
                    onClick={() => handleRowClick(row)}
                    className={className}
                    style={rowStyle?.(row)}
                  >
                    {cells}
                  </motion.tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>,
      desktopDrag,
      )}
    </>
  )
}
