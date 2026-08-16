import "./globals.css"
import type { Metadata } from "next"
import { NavigationBar } from "@/app/_components/NavigationBar"
import { Toaster } from "react-hot-toast"
import { ViewProvider } from "./context/ViewContext"
import { MediaPlayerProvider } from "@/app/context/MediaPlayerContext"
import { AuthProvider } from "@/app/context/AuthContext"
import { AdminProvider } from "@/app/context/AdminContext"
import { AuthGuard } from "@/app/_components/AuthGuard"
import { ThumbnailFilters } from "@/app/_components/ThumbnailFilters"

export const metadata: Metadata = {
  title: "Ytdl-Hoarder",
  description: "Helper for managing YouTube downloads",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" data-theme="matrix">
      <body className="font-sans">
        <Toaster
          position="bottom-left"
          containerStyle={{ zIndex: 99999 }}
          toastOptions={{
            style: {
              background: "var(--card-bg)",
              color: "var(--text-primary)",
              border: "1px solid var(--matrix-green)",
              borderRadius: "var(--radius)",
              boxShadow: "var(--shadow-glow)",
              fontFamily: "var(--font-sans)",
            },
            success: {
              style: {
                borderLeft: "4px solid var(--status-success)",
              },
              iconTheme: {
                primary: "var(--status-success)",
                secondary: "var(--bg-void)",
              },
            },
            error: {
              style: {
                borderLeft: "4px solid var(--status-error)",
              },
              iconTheme: {
                primary: "var(--status-error)",
                secondary: "var(--bg-void)",
              },
            },
          }}
        />
        <ThumbnailFilters />
        <AuthProvider>
          <AuthGuard>
            <AdminProvider>
            <MediaPlayerProvider>
              <ViewProvider>
                <div className="min-h-screen bg-bg-void bg-grid">
                  <NavigationBar />
                  {children}
                </div>
              </ViewProvider>
            </MediaPlayerProvider>
            </AdminProvider>
          </AuthGuard>
        </AuthProvider>
      </body>
    </html>
  )
}
