"use client"

import { useState, useCallback } from "react"
import { useFetchEffect } from "@/app/_hooks/useFetchEffect"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Settings } from "@/app/types/Settings"
import { ArrowPathIcon, CheckIcon } from "@heroicons/react/24/outline"
import axios from "axios"
import toast from "react-hot-toast"
import { apiUrl, errorMessage } from "@/app/lib/api"
import { motion } from "framer-motion"
import { cn } from "@/lib/utils"
import { useAuth } from "@/app/context/AuthContext"
import { SETTINGS_CONFIG } from "./settings/config"
import { SettingsSection } from "./settings/SettingsSection"
import { CookieFileSection } from "./settings/CookieFileSection"
import { UserManagement } from "./settings/UserManagement"

export function SettingsCard() {
  const { user } = useAuth()
  const [settings, setSettings] = useState<Settings | null>(null)
  const [localValues, setLocalValues] = useState<Partial<Settings>>({})
  const [saving, setSaving] = useState(false)
  const [resettingKey, setResettingKey] = useState<string | null>(null)
  const [resettingAll, setResettingAll] = useState(false)

  const fetchSettings = useCallback(async () => {
    try {
      const response = await axios.get(apiUrl('/settings'))
      setSettings(response.data)
      setLocalValues({})
    } catch (error) {
      console.error("Failed to fetch settings:", error)
      toast.error("Failed to load settings")
    }
  }, [])

  const { isLoading: loading } = useFetchEffect(fetchSettings, [fetchSettings], {
    initialLoading: true,
  })

  const handleValueChange = (key: keyof Settings, value: number | string[] | boolean) => {
    setLocalValues((prev) => ({ ...prev, [key]: value }))
  }

  const hasChanges = Object.keys(localValues).some(
    (key) =>
      JSON.stringify(localValues[key as keyof Settings]) !==
      JSON.stringify(settings?.[key as keyof Settings])
  )

  const handleSave = async () => {
    if (!hasChanges) return

    setSaving(true)
    try {
      const response = await axios.put(
        apiUrl('/settings'),
        localValues
      )
      setSettings(response.data)
      setLocalValues({})
      toast.success("Settings saved successfully")
    } catch (error) {
      console.error("Failed to save settings:", error)
      toast.error(errorMessage(error, "Failed to save settings"))
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async (key: string) => {
    setResettingKey(key)
    try {
      const response = await axios.put(
        apiUrl(`/settings/reset/${key}`)
      )
      setSettings(response.data)
      setLocalValues((prev) => {
        const newValues = { ...prev }
        delete newValues[key as keyof Settings]
        return newValues
      })
      toast.success(`Reset ${key} to default`)
    } catch (error) {
      console.error("Failed to reset setting:", error)
      toast.error(errorMessage(error, "Failed to reset setting"))
    } finally {
      setResettingKey(null)
    }
  }


  const handleResetAll = async () => {
    if (!window.confirm("Are you sure you want to reset all settings to their defaults?")) {
      return
    }

    setResettingAll(true)
    try {
      const response = await axios.put(
        apiUrl('/settings/reset')
      )
      setSettings(response.data)
      setLocalValues({})
      toast.success("All settings reset to defaults")
    } catch (error) {
      console.error("Failed to reset all settings:", error)
      toast.error(errorMessage(error, "Failed to reset settings"))
    } finally {
      setResettingAll(false)
    }
  }

  if (loading) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="flex items-center justify-center py-12"
      >
        <div className="flex items-center gap-3 text-text-muted">
          <ArrowPathIcon className="h-5 w-5 animate-spin" />
          <span className="font-mono text-sm">Loading settings...</span>
        </div>
      </motion.div>
    )
  }

  if (!settings) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="flex items-center justify-center py-12"
      >
        <div className="text-text-muted font-mono text-sm">Failed to load settings</div>
      </motion.div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="space-y-6"
    >
      {/* Header with actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Application Settings</h2>
          <p className="text-sm text-text-muted mt-1">
            Configure download behavior, transcript generation, and display options.
            Changes take effect on next task execution.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleResetAll}
            disabled={resettingAll}
          >
            {resettingAll ? (
              <ArrowPathIcon className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <ArrowPathIcon className="h-4 w-4 mr-2" />
            )}
            Reset All
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={!hasChanges || saving}
            className={cn(
              "transition-all",
              hasChanges && "bg-matrix hover:bg-matrix/90"
            )}
          >
            {saving ? (
              <ArrowPathIcon className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <CheckIcon className="h-4 w-4 mr-2" />
            )}
            Save Changes
          </Button>
        </div>
      </div>

      {/* Download Settings */}
      <SettingsSection
        title="Download Settings"
        description="Configure yt-dlp download behavior and rate limiting"
        settings={SETTINGS_CONFIG.download}
        values={settings}
        localValues={localValues}
        onValueChange={handleValueChange}
        onReset={handleReset}
        resettingKey={resettingKey}
      />

      {/* Tasks */}
      <SettingsSection
        title="Tasks"
        description="How often subscriptions are checked and how many jobs each orchestrator lane runs at once — applied immediately, without a restart"
        settings={SETTINGS_CONFIG.tasks}
        values={settings}
        localValues={localValues}
        onValueChange={handleValueChange}
        onReset={handleReset}
        resettingKey={resettingKey}
      />

      {/* Cookie Authentication */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Cookie Authentication</CardTitle>
          <CardDescription>Provide cookies for downloading age-restricted or member-only content</CardDescription>
        </CardHeader>
        <CardContent>
          <CookieFileSection />
        </CardContent>
      </Card>

      {/* Transcript Settings */}
      <SettingsSection
        title="Transcript Settings"
        description="Configure audio transcription chunk and block sizes"
        settings={SETTINGS_CONFIG.transcript}
        values={settings}
        localValues={localValues}
        onValueChange={handleValueChange}
        onReset={handleReset}
        resettingKey={resettingKey}
      />

      {/* Display Settings */}
      <SettingsSection
        title="Display Settings"
        description="Configure table pagination and UI preferences"
        settings={SETTINGS_CONFIG.display}
        values={settings}
        localValues={localValues}
        onValueChange={handleValueChange}
        onReset={handleReset}
        resettingKey={resettingKey}
      />

      {/* User Management - Admin only */}
      {user?.is_admin && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">User Management</CardTitle>
            <CardDescription>Manage users, approve registrations, and configure access</CardDescription>
          </CardHeader>
          <CardContent>
            <UserManagement />
          </CardContent>
        </Card>
      )}

      {/* Last updated */}
      <div className="text-xs text-text-muted text-right font-mono">
        Last updated: {new Date(settings.updated_at).toLocaleString()}
      </div>
    </motion.div>
  )
}
