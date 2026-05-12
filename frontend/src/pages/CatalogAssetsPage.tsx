import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'
import {
  Check,
  ChevronRight,
  Edit2,
  Folder,
  FolderPlus,
  Image as ImageIcon,
  Loader2,
  Search,
  Square,
  Trash2,
  Upload,
  X,
} from 'lucide-react'

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

function prefixSegments(prefix: string): string[] {
  return prefix.split('/').filter(Boolean)
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
  const [folders, setFolders] = useState<string[]>([])
  const [currentPrefix, setCurrentPrefix] = useState('')
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

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [mergeModalOpen, setMergeModalOpen] = useState(false)
  const [mergeFolderName, setMergeFolderName] = useState('')
  const [merging, setMerging] = useState(false)
  const [availableFolders, setAvailableFolders] = useState<string[]>([])
  const [loadingAvailableFolders, setLoadingAvailableFolders] = useState(false)

  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [renaming, setRenaming] = useState(false)

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

  const loadPage = useCallback(
    async (mode: 'reset' | 'append', pageCursor: string | null) => {
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
          prefix: currentPrefix || undefined,
        })

        setItems((prev) => (mode === 'append' ? mergeUnique(prev, response.items) : response.items))
        if (mode === 'reset') {
          setFolders(response.folders ?? [])
        }
        setCursor(response.next_cursor ?? null)
        setTotalCount(response.total_count)
        setError('')
      } catch (err) {
        setError(parseError(err, 'Katalog görselleri yüklenemedi'))
      } finally {
        if (mode === 'append') {
          loadingMoreRef.current = false
          setLoadingMore(false)
        } else setLoadingInitial(false)
      }
    },
    [searchQuery, currentPrefix],
  )

  useEffect(() => {
    setCursor(null)
    setSelected(new Set())
    void loadPage('reset', null)
  }, [searchQuery, currentPrefix, loadPage])

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
      const response = await api.uploadCatalogAssetsBulk(fileList, currentPrefix || undefined)
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
      setSelected((prev) => {
        if (!prev.has(key)) return prev
        const next = new Set(prev)
        next.delete(key)
        return next
      })
      setTotalCount((prev) => Math.max(0, prev - 1))
    } catch (err) {
      setError(parseError(err, 'Görsel silinemedi'))
    } finally {
      setDeletingKey('')
    }
  }

  const toggleSelected = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const clearSelection = () => setSelected(new Set())

  const openMergeModal = () => {
    if (selected.size === 0) return
    setMergeFolderName('')
    setError('')
    setUploadSummary('')
    setMergeModalOpen(true)

    // Backend creates folders at root level only, so always fetch root folders
    // regardless of where the user currently is.
    setLoadingAvailableFolders(true)
    void (async () => {
      try {
        const response = await api.listCatalogAssets({ limit: 1 })
        setAvailableFolders(response.folders ?? [])
      } catch {
        setAvailableFolders([])
      } finally {
        setLoadingAvailableFolders(false)
      }
    })()
  }

  const handleMergeIntoFolder = async () => {
    const trimmed = mergeFolderName.trim()
    if (!trimmed) return
    setMerging(true)
    setError('')
    setUploadSummary('')
    try {
      const response = await api.moveCatalogAssetsIntoFolder(trimmed, Array.from(selected))
      const { success_count, failure_count, results } = response
      if (failure_count > 0) {
        const failedNames = results
          .filter((r) => !r.success)
          .map((r) => `${r.key}${r.error ? ` (${r.error})` : ''}`)
          .join(', ')
        setError(`${failure_count} görsel taşınamadı: ${failedNames}`)
      }
      if (success_count > 0) {
        setUploadSummary(`${success_count} görsel "${trimmed}" klasörüne taşındı.`)
      }
      setMergeModalOpen(false)
      setMergeFolderName('')
      setSelected(new Set())
      setCursor(null)
      await loadPage('reset', null)
    } catch (err) {
      setError(parseError(err, 'Klasör oluşturulamadı'))
    } finally {
      setMerging(false)
    }
  }

  const startRename = (item: CatalogAssetItem) => {
    setEditingKey(item.key)
    setEditingName(item.name)
    setError('')
    setUploadSummary('')
  }

  const cancelRename = () => {
    setEditingKey(null)
    setEditingName('')
  }

  const submitRename = async () => {
    if (!editingKey) return
    const newName = editingName.trim()
    if (!newName) return
    setRenaming(true)
    setError('')
    try {
      const response = await api.renameCatalogAsset(editingKey, newName)
      // Update local items in-place.
      setItems((prev) =>
        prev.map((item) =>
          item.key === editingKey
            ? {
                ...item,
                key: response.new_key,
                name: response.new_key.split('/').pop() ?? response.new_key,
                content_url: `/v1/catalog-assets/${encodeURIComponent(response.new_key)}/content`,
              }
            : item,
        ),
      )
      setEditingKey(null)
      setEditingName('')
      setUploadSummary(`"${response.old_key}" → "${response.new_key}" olarak yeniden adlandırıldı.`)
    } catch (err) {
      setError(parseError(err, 'Yeniden adlandırılamadı'))
    } finally {
      setRenaming(false)
    }
  }

  const enterFolder = (folderName: string) => {
    if (!folderName) return
    setCurrentPrefix((prev) => `${prev}${folderName}/`)
  }

  const navigateToSegment = (idx: number) => {
    // idx === -1 → root, otherwise rebuild prefix from first idx+1 segments
    const segs = prefixSegments(currentPrefix)
    if (idx < 0) {
      setCurrentPrefix('')
      return
    }
    setCurrentPrefix(segs.slice(0, idx + 1).join('/') + '/')
  }

  const summaryText = useMemo(() => {
    if (searchQuery) return `${totalCount} sonuç`
    return `${items.length} / ${totalCount} görsel · ${folders.length} klasör`
  }, [items.length, searchQuery, totalCount, folders.length])

  const segs = prefixSegments(currentPrefix)
  const allItemKeysOnPage = items.map((it) => it.key)
  const allSelectedOnPage = allItemKeysOnPage.length > 0 && allItemKeysOnPage.every((k) => selected.has(k))
  const toggleSelectAllOnPage = () => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (allSelectedOnPage) {
        for (const k of allItemKeysOnPage) next.delete(k)
      } else {
        for (const k of allItemKeysOnPage) next.add(k)
      }
      return next
    })
  }

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }} className="space-y-6">
        <div>
          <h1 className="text-3xl mb-1" style={{ fontFamily: 'var(--font-display)' }}>
            Katalog Görselleri
          </h1>
          <p className="text-muted-foreground">MinIO catalog bucket içeriğini görüntüle, ara, yükle, klasörle ve sil.</p>
        </div>

        {/* Breadcrumb */}
        <nav className="flex items-center gap-1 text-sm">
          <button
            type="button"
            onClick={() => navigateToSegment(-1)}
            className={`px-2 py-1 rounded-md hover:bg-accent ${segs.length === 0 ? 'font-medium text-foreground' : 'text-muted-foreground'}`}
          >
            Root
          </button>
          {segs.map((seg, idx) => (
            <div key={`${seg}-${idx}`} className="flex items-center gap-1">
              <ChevronRight className="w-3 h-3 text-muted-foreground" />
              <button
                type="button"
                onClick={() => navigateToSegment(idx)}
                className={`px-2 py-1 rounded-md hover:bg-accent ${idx === segs.length - 1 ? 'font-medium text-foreground' : 'text-muted-foreground'}`}
              >
                {seg}
              </button>
            </div>
          ))}
        </nav>

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
              {items.length > 0 ? (
                <button
                  type="button"
                  onClick={toggleSelectAllOnPage}
                  className="inline-flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-accent"
                  title={allSelectedOnPage ? 'Seçimi kaldır' : 'Bu sayfadaki tüm görselleri seç'}
                >
                  {allSelectedOnPage ? <Check className="w-4 h-4" /> : <Square className="w-4 h-4" />}
                  {allSelectedOnPage ? 'Seçimi Temizle' : 'Tümünü Seç'}
                </button>
              ) : null}
              <button
                type="button"
                onClick={openFilePicker}
                disabled={uploading}
                className="inline-flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50"
              >
                {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                Görsel Yükle{currentPrefix ? ` (${segs[segs.length - 1]})` : ''}
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

        {/* Selection action bar */}
        {selected.size > 0 ? (
          <div className="sticky top-2 z-10 rounded-2xl border border-primary/40 bg-primary/10 backdrop-blur px-4 py-3 flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium text-foreground">{selected.size} görsel seçildi</span>
            <button
              type="button"
              onClick={openMergeModal}
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              <FolderPlus className="w-4 h-4" />
              Klasör Olarak Birleştir
            </button>
            <button
              type="button"
              onClick={clearSelection}
              className="inline-flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-1.5 text-sm font-medium hover:bg-accent"
            >
              <X className="w-4 h-4" />
              Seçimi Temizle
            </button>
          </div>
        ) : null}

        {/* Folders */}
        {!searchQuery && folders.length > 0 ? (
          <div>
            <h2 className="text-sm font-medium text-muted-foreground mb-2">Klasörler</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
              {folders.map((folderName) => (
                <button
                  key={folderName}
                  type="button"
                  onClick={() => enterFolder(folderName)}
                  className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-3 text-left text-sm hover:bg-accent transition"
                >
                  <Folder className="w-5 h-5 text-amber-500 shrink-0" />
                  <span className="truncate font-medium" title={folderName}>
                    {folderName}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {loadingInitial ? (
          <div className="rounded-2xl border border-border bg-card px-6 py-12 text-center text-sm text-muted-foreground">Yükleniyor...</div>
        ) : items.length === 0 && folders.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border bg-card px-6 py-12 text-center text-sm text-muted-foreground">
            {searchQuery ? 'Sonuç bulunamadı.' : currentPrefix ? 'Bu klasör boş.' : 'Henüz görsel yok.'}
          </div>
        ) : (
          <>
            {items.length > 0 ? (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {items.map((item) => {
                  const isSelected = selected.has(item.key)
                  const isEditing = editingKey === item.key
                  return (
                    <div
                      key={item.key}
                      className={`relative rounded-2xl border bg-card p-3 shadow-sm transition ${
                        isSelected ? 'border-primary ring-2 ring-primary/30' : 'border-border'
                      }`}
                    >
                      {/* Selection toggle (top-left overlay) */}
                      <button
                        type="button"
                        onClick={() => toggleSelected(item.key)}
                        className={`absolute top-5 left-5 z-10 w-7 h-7 rounded-md flex items-center justify-center border ${
                          isSelected
                            ? 'bg-primary border-primary text-primary-foreground'
                            : 'bg-background/80 border-border text-muted-foreground hover:text-foreground'
                        }`}
                        aria-label={isSelected ? 'Seçimi kaldır' : 'Seç'}
                        title={isSelected ? 'Seçimi kaldır' : 'Seç'}
                      >
                        {isSelected ? <Check className="w-4 h-4" /> : <Square className="w-4 h-4" />}
                      </button>

                      <AssetThumbnail item={item} />

                      <div className="mt-3 space-y-1">
                        {isEditing ? (
                          <div className="flex items-center gap-1">
                            <input
                              type="text"
                              value={editingName}
                              onChange={(e) => setEditingName(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') void submitRename()
                                if (e.key === 'Escape') cancelRename()
                              }}
                              autoFocus
                              disabled={renaming}
                              className="flex-1 min-w-0 rounded-md border border-primary bg-background px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                            />
                            <button
                              type="button"
                              onClick={() => void submitRename()}
                              disabled={renaming || !editingName.trim()}
                              className="p-1 rounded-md text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                              title="Kaydet"
                            >
                              {renaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                            </button>
                            <button
                              type="button"
                              onClick={cancelRename}
                              disabled={renaming}
                              className="p-1 rounded-md text-muted-foreground hover:bg-accent disabled:opacity-50"
                              title="İptal"
                            >
                              <X className="w-4 h-4" />
                            </button>
                          </div>
                        ) : (
                          <p className="text-sm font-medium text-foreground truncate" title={item.key}>
                            {item.name}
                          </p>
                        )}
                        <p className="text-xs text-muted-foreground">{formatBytes(item.size)}</p>
                      </div>

                      <div className="mt-3 flex justify-end gap-2">
                        {!isEditing ? (
                          <button
                            type="button"
                            onClick={() => startRename(item)}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
                            title="Yeniden adlandır"
                          >
                            <Edit2 className="w-3 h-3" />
                            Yeniden Adlandır
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => void handleDelete(item.key)}
                          disabled={deletingKey === item.key}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-2.5 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                          title="Sil"
                        >
                          {deletingKey === item.key ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                          Sil
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : null}

            <div ref={sentinelRef} className="h-10 flex items-center justify-center text-xs text-muted-foreground">
              {loadingMore ? <Loader2 className="w-4 h-4 animate-spin" /> : cursor ? 'Daha fazla yüklemek için aşağı kaydır' : items.length > 0 ? 'Tüm görseller yüklendi' : ''}
            </div>
          </>
        )}
      </motion.div>

      {/* Merge into folder modal */}
      {mergeModalOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget && !merging) setMergeModalOpen(false)
          }}
        >
          <div className="w-full max-w-md rounded-2xl border border-border bg-card shadow-xl p-5 space-y-4">
            <div className="flex items-start gap-3">
              <div className="rounded-xl bg-primary/10 p-2">
                <FolderPlus className="w-5 h-5 text-primary" />
              </div>
              <div className="flex-1">
                <h2 className="text-lg font-medium">Klasöre Taşı</h2>
                <p className="text-sm text-muted-foreground mt-0.5">
                  {selected.size} seçili görsel için mevcut bir klasöre ekle veya yeni klasör oluştur.
                </p>
              </div>
            </div>

            {/* Existing folders */}
            <div>
              <label className="text-sm font-medium block mb-1.5">Mevcut Klasörler</label>
              {loadingAvailableFolders ? (
                <div className="text-xs text-muted-foreground flex items-center gap-2">
                  <Loader2 className="w-3 h-3 animate-spin" /> Yükleniyor...
                </div>
              ) : availableFolders.length === 0 ? (
                <p className="text-xs text-muted-foreground">Henüz klasör yok. Aşağıya bir isim yazarak yeni klasör oluştur.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {availableFolders.map((name) => {
                    const isPicked = mergeFolderName.trim() === name
                    return (
                      <button
                        key={name}
                        type="button"
                        onClick={() => setMergeFolderName(name)}
                        disabled={merging}
                        className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition disabled:opacity-50 ${
                          isPicked
                            ? 'border-primary bg-primary/15 text-foreground'
                            : 'border-border bg-background hover:bg-accent text-foreground'
                        }`}
                        title={`'${name}' klasörüne ekle`}
                      >
                        <Folder className="w-3 h-3 text-amber-500" />
                        {name}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            <div>
              <label className="text-sm font-medium block mb-1.5">Klasör Adı</label>
              <input
                type="text"
                value={mergeFolderName}
                onChange={(e) => setMergeFolderName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && mergeFolderName.trim()) void handleMergeIntoFolder()
                  if (e.key === 'Escape' && !merging) setMergeModalOpen(false)
                }}
                placeholder="örn: hayvanlar (mevcuta eklemek için yukarıdan seç)"
                autoFocus
                disabled={merging}
                className="w-full rounded-xl border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Mevcut bir klasör adı yazarsan görsel oraya eklenir; yeni bir isim yazarsan klasör oluşturulur. <code>/</code>, <code>\</code> ve <code>..</code> içeremez.
              </p>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setMergeModalOpen(false)}
                disabled={merging}
                className="inline-flex items-center rounded-xl border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50"
              >
                İptal
              </button>
              <button
                type="button"
                onClick={() => void handleMergeIntoFolder()}
                disabled={merging || !mergeFolderName.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                {merging ? <Loader2 className="w-4 h-4 animate-spin" /> : <FolderPlus className="w-4 h-4" />}
                {availableFolders.includes(mergeFolderName.trim()) ? 'Klasöre Ekle' : 'Klasör Oluştur'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
