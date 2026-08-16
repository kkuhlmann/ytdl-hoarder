"use client"

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Settings, SettingMeta } from "@/app/types/Settings"
import { SettingField } from "./SettingField"

type SettingsSectionProps = {
  title: string
  description: string
  settings: SettingMeta[]
  values: Settings
  localValues: Partial<Settings>
  onValueChange: (key: keyof Settings, value: number | string[] | boolean) => void
  onReset: (key: string) => void
  resettingKey: string | null
}

export function SettingsSection({
  title,
  description,
  settings,
  values,
  localValues,
  onValueChange,
  onReset,
  resettingKey,
}: SettingsSectionProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {settings.map((meta) => {
          const currentValue = localValues[meta.key] ?? values[meta.key]
          const originalValue = values[meta.key]
          const isModified = JSON.stringify(currentValue) !== JSON.stringify(originalValue)

          return (
            <SettingField
              key={meta.key}
              meta={meta}
              value={currentValue as number | string[] | boolean}
              onChange={(v) => onValueChange(meta.key, v)}
              onReset={() => onReset(meta.key)}
              isModified={isModified}
              isResetting={resettingKey === meta.key}
            />
          )
        })}
      </CardContent>
    </Card>
  )
}
