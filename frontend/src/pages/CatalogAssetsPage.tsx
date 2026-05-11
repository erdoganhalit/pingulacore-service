import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { Image as ImageIcon, Loader2, Search, Trash2, Upload } from 'lucide-react'

import { ApiError, api } from '../lib/api'
import { fetchBlobFromUrl } from '../lib/download'
import type { CatalogAssetItem } from '../types'

const PAGE_SIZE = 10

function parseError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error && error.message) return error.message
  return fallback
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(2)} MB`
}

function mergeUnique(prev: CatalogAssetItem[], next: CatalogAssetItem[]): CatalogAssetItem[] {
  const map = new Map(prev.map((item) => [item.key, item]))
  for (const item of next) map.set(item.key, item)
  return Array.from(map.values())
}

function AssetThumbnail({ item }: { item: CatalogAssetItem }) {
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    void (async () => {
      try {
        const blob = await fetchBlobFromUrl(item.content_url)
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setSrc(objectUrl)
      } catch {
        if (active) setSrc(null)
      }
    })()

    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [item.content_url])

  if (!src) {
    return (
      <div className="h-44 rounded-xl border border-border bg-muted/40 flex items-center justify-center text-muted-foreground text-sm">
        <ImageIcon className="w-5 h-5 mr-2" />
        Önizleme yok
      </div>
    )
  }

  return <img src={src} alt={item.name} className="h-44 w-full rounded-xl border border-border object-cover" loading="lazy" />
}

export function CatalogAssetsPage() {
  const [items, setItems] = useState<CatalogAssetItem[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [totalCount, setTotalCount] = useState(0)
  const [loadingInitial, setLoadingInitial] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deletingKey, setDeletingKey] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [error, setError] = useState('')
  const [uploadSummary, setUploadSummary] = useState('')

  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const loadingMoreRef = useRef(false)

  useEffect(() => {
    loadingMoreRef.current = loadingMore
  }, [loadingMore])

  useEffect(() => {
    const id = window.setTimeout(() => {
      setSearchQuery(searchInput.trim())
    }, 250)
    return () => window.clearTimeout(id)
  }, [searchInput])

  const loadPage = useCallback(async (mode: 'reset' | 'append', pageCursor: string | null) => {
    if (mode === 'append') {
      if (loadingMoreRef.current || pageCursor === null) return
      loadingMoreRef.current = true
      setLoadingMore(true)
    } else {
      setLoadingInitial(true)
    }

    try {
      const response = await api.listCatalogAssets({
        cursor: mode === 'append' ? pageCursor ?? undefined : undefined,
        limit: PAGE_SIZE,
        query: searchQuery || undefined,
      })

      setItems((prev) => (mode === 'append' ? mergeUnique(prev, response.items) : response.items))
      setCursor(response.next_cursor ?? null)
      setTotalCount(response.total_count)
      setError('')
    } catch (err) {
      setError(parseError(err, 'Katalog görselleri yüklenemedi'))
    } finally {
      if (mode === 'append') {
        loadingMoreRef.current = false
        setLoadingMore(false)
      }
      else setLoadingInitial(false)
    }
  }, [searchQuery])

  useEffect(() => {
    setCursor(null)
    void loadPage('reset', null)
  }, [searchQuery, loadPage])

  useEffect(() => {
    const node = sentinelRef.current
    if (!node) return
    if (cursor === null || loadingInitial || loadingMore) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          void loadPage('append', cursor)
        }
      },
      { rootMargin: '240px 0px' },
    )

    observer.observe(node)
    return () => observer.disconnect()
  }, [cursor, loadPage, loadingInitial, loadingMore])

  const openFilePicker = () => fileInputRef.current?.click()

  const handleUploadFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    const fileList = Array.from(files)
    setUploading(true)
    setError('')
    setUploadSummary('')
    try {
      const response = await api.uploadCatalogAssetsBulk(fileList)
      const { success_count, failure_count, results } = response
      if (failure_count > 0) {
        const failedNames = results
          .filter((r) => !r.success)
          .map((r) => `${r.filename}${r.error ? ` (${r.error})` : ''}`)
          .join(', ')
        setError(`${failure_count} dosya yüklenemedi: ${failedNames}`)
      }
      if (success_count > 0) {
        setUploadSummary(`${success_count} görsel başarıyla yüklendi.`)
      }
      setCursor(null)
      await loadPage('reset', null)
    } catch (err) {
      setError(parseError(err, 'Görsel yüklenemedi'))
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleDelete = async (key: string) => {
    const ok = window.confirm(`"${key}" görselini silmek istediğine emin misin?`)
    if (!ok) return
    setDeletingKey(key)
    setError('')
    try {
      await api.deleteCatalogAsset(key)
      setItems((prev) => prev.filter((item) => item.key !== key))
      setTotalCount((prev) => Math.max(0, prev - 1))
    } catch (err) {
      setError(parseError(err, 'Görsel silinemedi'))
    } finally {
      setDeletingKey('')
    }
  }

  const summaryText = useMemo(() => {
    if (searchQuery) return `${totalCount} sonuç`
    return `${items.length} / ${totalCount} görsel yüklendi`
  }, [items.length, searchQuery, totalCount])

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }} className="space-y-6">
        <div>
          <h1 className="text-3xl mb-1" style={{ fontFamily: 'var(--font-display)' }}>
            Katalog Görselleri
          </h1>
          <p className="text-muted-foreground">MinIO catalog bucket içeriğini görüntüle, ara, yükle ve sil.</p>
        </div>

        {error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        ) : null}

        {uploadSummary ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{uploadSummary}</div>
        ) : null}

        <div className="rounded-2xl border border-border bg-card shadow-sm p-4 md:p-5">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Asset ara: örn. ağaç, kitap, sepet..."
                className="w-full rounded-xl border border-border bg-background pl-9 pr-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>
            <div className="flex items-center gap-3">
              <p className="text-sm text-muted-foreground">{summaryText}</p>
              <button
                type="button"
                onClick={openFilePicker}
                disabled={uploading}
                className="inline-flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50"
              >
                {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />} Görsel Yükle
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                onChange={(e) => void handleUploadFiles(e.target.files)}
                className="hidden"
              />
            </div>
          </div>
        </div>

        {loadingInitial ? (
          <div className="rounded-2xl border border-border bg-card px-6 py-12 text-center text-sm text-muted-foreground">Yükleniyor...</div>
        ) : items.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border bg-card px-6 py-12 text-center text-sm text-muted-foreground">
            Sonuç bulunamadı.
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {items.map((item) => (
                <div key={item.key} className="rounded-2xl border border-border bg-card p-3 shadow-sm">
                  <AssetThumbnail item={item} />
                  <div className="mt-3 space-y-1">
                    <p className="text-sm font-medium text-foreground truncate" title={item.key}>
                      {item.name}
                    </p>
                    <p className="text-xs text-muted-foreground">{formatBytes(item.size)}</p>
                  </div>
                  <div className="mt-3 flex justify-end">
                    <button
                      type="button"
                      onClick={() => void handleDelete(item.key)}
                      disabled={deletingKey === item.key}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-2.5 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                    >
                      {deletingKey === item.key ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                      Sil
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div ref={sentinelRef} className="h-10 flex items-center justify-center text-xs text-muted-foreground">
              {loadingMore ? <Loader2 className="w-4 h-4 animate-spin" /> : cursor ? 'Daha fazla yüklemek için aşağı kaydır' : 'Tüm görseller yüklendi'}
            </div>
          </>
        )}
      </motion.div>
    </div>
  )
}
