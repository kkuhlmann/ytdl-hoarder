"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { CalendarIcon } from "@heroicons/react/24/outline"
import { format } from "date-fns"
import { DayPicker, getDefaultClassNames } from "@daypicker/react"
import { cn } from "@/lib/utils"

type DateSelectionProps = {
  label: string
  className?: string
  date: Date | null | undefined
  setDate: (date: Date | null) => void
  options: any
  setOptions: (options: any) => void
}

export default function DateSelection({
  label,
  className,
  date,
  setDate,
  options,
  setOptions,
}: DateSelectionProps) {
  const [open, setOpen] = useState(false)

  const handleDateChange = (selectedDate: Date | undefined) => {
    if (selectedDate) {
      setDate(selectedDate)
      const value = selectedDate.toISOString()
      setOptions({ ...options, date_filter: value })
      setOpen(false)
    }
  }

  const defaultClassNames = getDefaultClassNames()

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cn(
            "w-full justify-start text-left font-mono h-9",
            !date && "text-text-muted",
            className
          )}
        >
          <CalendarIcon className="mr-2 h-4 w-4" />
          {date ? format(date, "PPP") : <span>{label}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <DayPicker
          mode="single"
          selected={date || undefined}
          onSelect={handleDateChange}
          captionLayout="dropdown"
          classNames={{
            root: `${defaultClassNames.root} rdp-matrix bg-bg-terminal p-3 font-mono`,
            months: `${defaultClassNames.months}`,
            month: `${defaultClassNames.month}`,
            month_caption: `${defaultClassNames.month_caption} text-text-primary font-mono text-sm mb-2`,
            caption_label: `${defaultClassNames.caption_label} text-text-primary`,
            nav: `${defaultClassNames.nav} flex gap-1`,
            button_previous: `${defaultClassNames.button_previous} text-text-secondary hover:text-matrix hover:bg-matrix/10 rounded p-1`,
            button_next: `${defaultClassNames.button_next} text-text-secondary hover:text-matrix hover:bg-matrix/10 rounded p-1`,
            chevron: `fill-current`,
            dropdowns: `${defaultClassNames.dropdowns} flex gap-2`,
            dropdown: `${defaultClassNames.dropdown} rdp-dropdown-matrix`,
            dropdown_root: `${defaultClassNames.dropdown_root}`,
            weekdays: `${defaultClassNames.weekdays}`,
            weekday: `${defaultClassNames.weekday} text-text-muted font-mono text-xs`,
            week: `${defaultClassNames.week}`,
            day: `${defaultClassNames.day} text-text-primary hover:bg-matrix/10 rounded text-sm`,
            day_button: `${defaultClassNames.day_button} w-8 h-8 flex items-center justify-center rounded transition-colors`,
            today: `${defaultClassNames.today} border border-matrix/50`,
            selected: `bg-matrix text-(--btn-text) font-semibold`,
            outside: `${defaultClassNames.outside} text-text-muted/50`,
            disabled: `${defaultClassNames.disabled} text-text-muted/30`,
            hidden: `${defaultClassNames.hidden}`,
          }}
        />
      </PopoverContent>
    </Popover>
  )
}
