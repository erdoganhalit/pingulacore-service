import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { motion } from 'motion/react'
import { ArrowLeft, ChevronDown, ChevronRight, Layers3, Lock, Plus, Sparkles, Trash2 } from 'lucide-react'

import { Modal } from '../components/Modal'
import { ApiError, api } from '../lib/api'
import type {
  CurriculumNodeItem,
  PropertyDataType,
  PropertyDefinitionItem,
} from '../types'

const DATA_TYPE_OPTIONS: PropertyDataType[] = ['text', 'bool', 'number', 'json', 'array', 'enum', 'object']

const inputClass =
  'w-full rounded-xl border-2 border-border bg-white px-4 py-3 text-sm text-foreground focus:outline-none focus:border-primary transition-colors'
const textareaClass = `${inputClass} min-h-[110px] resize-y`
const selectClass = inputClass

function parseError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error && error.message) return error.message
  return fallback
}

function toSchemaKey(value: string): string {
  return value
    .toLowerCase()
    .replace(/ı/g, 'i')
    .replace(/ş/g, 's')
    .replace(/ğ/g, 'g')
    .replace(/ü/g, 'u')
    .replace(/ö/g, 'o')
    .replace(/ç/g, 'c')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

function findCurriculumNode(nodes: CurriculumNodeItem[], targetId: string): CurriculumNodeItem | null {
  for (const node of nodes) {
    if (node.id === targetId) return node
    const child = findCurriculumNode(node.children, targetId)
    if (child) return child
  }
  return null
}

interface PropertyTreeNode {
  property: PropertyDefinitionItem
  children: PropertyTreeNode[]
}

function buildPropertyTree(items: PropertyDefinitionItem[], sortOrder: 'created' | 'alpha'): PropertyTreeNode[] {
  const byId = new Map<string, PropertyTreeNode>()
  for (const item of items) byId.set(item.id, { property: item, children: [] })
  const roots: PropertyTreeNode[] = []
  for (const item of items) {
    const node = byId.get(item.id)!
    if (item.parent_property_id && byId.has(item.parent_property_id)) {
      byId.get(item.parent_property_id)!.children.push(node)
    } else {
      roots.push(node)
    }
  }
  const compare = sortOrder === 'alpha'
    ? (a: PropertyTreeNode, b: PropertyTreeNode) => a.property.label.localeCompare(b.property.label, 'tr')
    : (a: PropertyTreeNode, b: PropertyTreeNode) => (a.property.created_at ?? '').localeCompare(b.property.created_at ?? '')
  const sortRec = (list: PropertyTreeNode[]) => {
    list.sort(compare)
    list.forEach((n) => sortRec(n.children))
  }
  sortRec(roots)
  return roots
}

interface AddFormState {
  label: string
  propertyKey: string
  canonicalPath: string
  dataType: PropertyDataType
  defaultValue: string
  description: string
  isRequired: boolean
}

const emptyForm: AddFormState = {
  label: '',
  propertyKey: '',
  canonicalPath: '',
  dataType: 'text',
  defaultValue: '',
  description: '',
  isRequired: false,
}

interface AddPropertyModalProps {
  open: boolean
  onClose: () => void
  parent: PropertyDefinitionItem | null
  currentNode: CurriculumNodeItem
  onCreated: () => Promise<void> | void
  setNotice: (msg: { tone: 'success' | 'error'; message: string }) => void
}

function AddPropertyModal({ open, onClose, parent, currentNode, onCreated, setNotice }: AddPropertyModalProps) {
  const [form, setForm] = useState<AddFormState>(emptyForm)
  const [keyTouched, setKeyTouched] = useState(false)
  const [pathTouched, setPathTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setForm(emptyForm)
    setKeyTouched(false)
    setPathTouched(false)
    setBusy(false)
    setError('')
  }, [open])

  const handleLabel = (value: string) => {
    const key = toSchemaKey(value)
    setForm((prev) => ({
      ...prev,
      label: value,
      propertyKey: keyTouched ? prev.propertyKey : key,
      canonicalPath: pathTouched
        ? prev.canonicalPath
        : parent
          ? `${parent.canonical_path}.${key}`
          : key,
    }))
  }

  const handleSubmit = async () => {
    setBusy(true)
    setError('')
    try {
      const label = form.label.trim()
      const key = form.propertyKey.trim()
      const path = form.canonicalPath.trim()
      if (!label || !key || !path) throw new Error('Label, property key ve canonical path zorunlu')
      await api.createProperty({
        defined_at_curriculum_node_id: currentNode.id,
        parent_property_id: parent?.id ?? null,
        label,
        description: form.description.trim() || null,
        property_key: key,
        canonical_path: path,
        data_type: form.dataType,
        default_value: form.dataType === 'object' ? null : form.defaultValue.trim() || null,
        is_required: form.isRequired,
      })
      setNotice({ tone: 'success', message: `Property eklendi: ${label}` })
      await onCreated()
      onClose()
    } catch (err) {
      setError(parseError(err, 'Property oluşturulamadı'))
    } finally {
      setBusy(false)
    }
  }

  const title = parent ? `Yeni Alan · ${parent.label} altına` : 'Yeni Kök Alan'

  return (
    <Modal open={open} onClose={onClose} title={title} size="wide">
      <div className="space-y-5 p-6">
        {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
        <div className="text-xs text-muted-foreground">
          Tanımlanacağı node: <span className="font-medium text-foreground">{currentNode.name}</span> · {currentNode.path}
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Etiket</label>
            <input value={form.label} onChange={(e) => handleLabel(e.target.value)} className={inputClass} />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Veri Tipi</label>
            <select
              value={form.dataType}
              onChange={(e) => {
                const next = e.target.value as PropertyDataType
                setForm((prev) => ({ ...prev, dataType: next, defaultValue: next === 'object' ? '' : prev.defaultValue }))
              }}
              className={selectClass}
            >
              {DATA_TYPE_OPTIONS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Property Anahtarı</label>
            <input
              value={form.propertyKey}
              onChange={(e) => {
                setKeyTouched(true)
                setForm((prev) => ({ ...prev, propertyKey: e.target.value }))
              }}
              className={inputClass}
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Kanonik Yol</label>
            <input
              value={form.canonicalPath}
              onChange={(e) => {
                setPathTouched(true)
                setForm((prev) => ({ ...prev, canonicalPath: e.target.value }))
              }}
              className={inputClass}
            />
          </div>
          <div className="space-y-1 md:col-span-2">
            <label className="text-xs font-medium text-muted-foreground">Açıklama</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
              className={textareaClass}
              rows={3}
            />
          </div>
          <div className="space-y-1 md:col-span-2">
            <label className="text-xs font-medium text-muted-foreground">Varsayılan Değer</label>
            <input
              value={form.defaultValue}
              onChange={(e) => setForm((prev) => ({ ...prev, defaultValue: e.target.value }))}
              className={inputClass}
              disabled={form.dataType === 'object'}
              placeholder={form.dataType === 'array' ? 'deger1;deger2;deger3' : 'Varsayılan değer'}
            />
            {form.dataType === 'array' ? (
              <div className="text-xs text-muted-foreground">Array tipinde öğeleri `;` ile ayır.</div>
            ) : null}
          </div>
          <label className="inline-flex items-center gap-2 rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground">
            <input
              type="checkbox"
              checked={form.isRequired}
              onChange={(e) => setForm((prev) => ({ ...prev, isRequired: e.target.checked }))}
            />
            Zorunlu alan
          </label>
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-xl border border-border bg-white px-4 py-2.5 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-60"
          >
            Vazgeç
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={busy}
            className="rounded-xl px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
            style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}
          >
            {busy ? 'Kaydediliyor...' : 'Property Ekle'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

interface PropertyTreeViewProps {
  roots: PropertyTreeNode[]
  currentNodeId: string
  curriculumNodeNames: Map<string, string>
  busy: boolean
  onAddChild: (parent: PropertyDefinitionItem) => void
  onDelete: (item: PropertyDefinitionItem) => void
}

function PropertyTreeView({ roots, currentNodeId, curriculumNodeNames, busy, onAddChild, onDelete }: PropertyTreeViewProps) {
  if (roots.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-background px-4 py-6 text-sm text-muted-foreground">
        Bu node ve atalarında tanımlı property bulunamadı.
      </div>
    )
  }
  return (
    <div className="space-y-2">
      {roots.map((root) => (
        <PropertyTreeRow
          key={root.property.id}
          node={root}
          currentNodeId={currentNodeId}
          curriculumNodeNames={curriculumNodeNames}
          busy={busy}
          onAddChild={onAddChild}
          onDelete={onDelete}
        />
      ))}
    </div>
  )
}

interface PropertyTreeRowProps {
  node: PropertyTreeNode
  currentNodeId: string
  curriculumNodeNames: Map<string, string>
  busy: boolean
  onAddChild: (parent: PropertyDefinitionItem) => void
  onDelete: (item: PropertyDefinitionItem) => void
}

function PropertyTreeRow({ node, currentNodeId, curriculumNodeNames, busy, onAddChild, onDelete }: PropertyTreeRowProps) {
  const [open, setOpen] = useState(true)
  const property = node.property
  const isOwned = property.defined_at_curriculum_node_id === currentNodeId
  const isObject = property.data_type === 'object'
  const hasChildren = node.children.length > 0
  const definedAtName = curriculumNodeNames.get(property.defined_at_curriculum_node_id) ?? '—'

  const cardClass = isOwned
    ? 'border-border bg-white'
    : 'border-border/60 bg-muted/30 opacity-70'
  const labelClass = isOwned ? 'text-foreground' : 'text-muted-foreground italic'

  return (
    <div className="space-y-1">
      <div className="flex items-start gap-2">
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setOpen((prev) => !prev)}
            className="mt-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-border bg-white text-muted-foreground hover:bg-accent"
            aria-label={open ? 'Daralt' : 'Genişlet'}
          >
            {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        ) : (
          <span className="mt-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-border/60 bg-background text-[10px] font-semibold text-muted-foreground">
            •
          </span>
        )}
        <div className={`flex-1 rounded-xl border px-3 py-2 ${cardClass}`}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <div className={`truncate text-sm font-medium ${labelClass}`}>{property.label}</div>
                <span className="rounded-full border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground">
                  {property.data_type}
                </span>
                {property.is_required ? (
                  <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">zorunlu</span>
                ) : null}
                {!isOwned ? (
                  <span className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 text-[11px] text-muted-foreground">
                    <Lock className="h-3 w-3" />
                    {definedAtName}
                  </span>
                ) : null}
              </div>
              <div className="mt-1 truncate text-xs text-muted-foreground">{property.canonical_path}</div>
              {property.description ? (
                <div className={`mt-1 text-xs ${isOwned ? 'text-muted-foreground' : 'text-muted-foreground/80'}`}>
                  {property.description}
                </div>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              {isObject ? (
                <button
                  type="button"
                  onClick={() => onAddChild(property)}
                  disabled={busy}
                  className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-border bg-white text-foreground hover:bg-accent disabled:opacity-60"
                  aria-label="Alt alan ekle"
                  title="Alt alan ekle"
                >
                  <Plus className="h-4 w-4" />
                </button>
              ) : null}
              {isOwned ? (
                <button
                  type="button"
                  onClick={() => onDelete(property)}
                  disabled={busy}
                  className="inline-flex h-7 shrink-0 items-center gap-1 rounded-lg border border-red-200 px-2 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
                  aria-label="Sil"
                  title="Sil"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Sil
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </div>
      {open && hasChildren ? (
        <div className="ml-6 border-l border-border/60 pl-3">
          {node.children.map((child) => (
            <PropertyTreeRow
              key={child.property.id}
              node={child}
              currentNodeId={currentNodeId}
              curriculumNodeNames={curriculumNodeNames}
              busy={busy}
              onAddChild={onAddChild}
              onDelete={onDelete}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function FieldsManagementPage() {
  const { nodeId = '' } = useParams<{ nodeId: string }>()
  const navigate = useNavigate()
  const [tree, setTree] = useState<CurriculumNodeItem[]>([])
  const [effective, setEffective] = useState<PropertyDefinitionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState<{ tone: 'success' | 'error'; message: string } | null>(null)
  const [addModal, setAddModal] = useState<{ open: boolean; parent: PropertyDefinitionItem | null }>({ open: false, parent: null })
  const [sortOrder, setSortOrder] = useState<'created' | 'alpha'>('created')

  const reload = async () => {
    if (!nodeId) return
    const props = await api.getEffectiveProperties(nodeId)
    setEffective(props)
  }

  useEffect(() => {
    void (async () => {
      setLoading(true)
      setError('')
      try {
        const [treeRows, props] = await Promise.all([
          api.getCurriculumTree(),
          nodeId ? api.getEffectiveProperties(nodeId) : Promise.resolve([] as PropertyDefinitionItem[]),
        ])
        setTree(treeRows)
        setEffective(props)
      } catch (err) {
        setError(parseError(err, 'Veriler yüklenemedi'))
      } finally {
        setLoading(false)
      }
    })()
  }, [nodeId])

  const currentNode = useMemo(() => (nodeId ? findCurriculumNode(tree, nodeId) : null), [tree, nodeId])

  const curriculumNodeNames = useMemo(() => {
    const map = new Map<string, string>()
    const walk = (nodes: CurriculumNodeItem[]) => {
      for (const n of nodes) {
        map.set(n.id, n.name)
        walk(n.children)
      }
    }
    walk(tree)
    return map
  }, [tree])

  const propertyRoots = useMemo(() => buildPropertyTree(effective, sortOrder), [effective, sortOrder])

  const handleAddChild = (parent: PropertyDefinitionItem) => {
    setAddModal({ open: true, parent })
  }

  const handleAddRoot = () => {
    setAddModal({ open: true, parent: null })
  }

  const handleDelete = async (item: PropertyDefinitionItem) => {
    if (!confirm(`Sil: ${item.label}?`)) return
    setBusy(true)
    try {
      await api.deleteProperty(item.id)
      await reload()
      setNotice({ tone: 'success', message: `Silindi: ${item.label}` })
    } catch (err) {
      setNotice({ tone: 'error', message: parseError(err, 'Property silinemedi') })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="p-8 max-w-[1680px] mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        className="space-y-6"
      >
        <div className="rounded-[28px] border border-border bg-card px-8 py-7 shadow-xl">
          <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-2xl text-white shadow-lg" style={{ background: 'linear-gradient(to bottom right, var(--primary), var(--secondary))' }}>
                <Sparkles className="h-7 w-7" />
              </div>
              <h1 className="text-4xl text-foreground" style={{ fontFamily: 'var(--font-display)' }}>
                {currentNode ? `${currentNode.name} · Alanları Yönet` : 'Alanları Yönet'}
              </h1>
              {currentNode ? (
                <p className="mt-2 text-sm text-muted-foreground">{currentNode.path}</p>
              ) : null}
              <p className="mt-2 text-lg text-muted-foreground">
                Bu node'da tanımlı ve atalardan miras alınan property'leri ağaç görünümünde yönet.
              </p>
            </div>
            <div className="rounded-2xl border border-border bg-background px-5 py-4 text-sm text-muted-foreground shadow-sm">
              <div className="flex items-center gap-2 font-medium text-foreground">
                <Layers3 className="h-4 w-4" />
                Etkin Özellikler
              </div>
              <div className="mt-1">
                Soluk satırlar atalardan miras; bu node için sadece okunabilir.
              </div>
            </div>
          </div>
        </div>

        {notice ? (
          <div
            className={`rounded-2xl border px-4 py-3 text-sm ${
              notice.tone === 'success'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : 'border-red-200 bg-red-50 text-red-700'
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div>{notice.message}</div>
              <button type="button" onClick={() => setNotice(null)} className="text-xs text-muted-foreground hover:text-foreground">
                Kapat
              </button>
            </div>
          </div>
        ) : null}

        {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

        {loading ? (
          <div className="rounded-2xl border border-border bg-card px-6 py-12 text-center text-sm text-muted-foreground shadow-sm">
            Yükleniyor...
          </div>
        ) : !currentNode ? (
          <div className="rounded-2xl border border-border bg-card px-6 py-12 text-center text-sm text-muted-foreground shadow-sm">
            Node bulunamadı.
          </div>
        ) : (
          <div className="rounded-2xl border border-border bg-card shadow-sm">
            <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
              {/* W */}
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => navigate('/content')}
                  className="inline-flex items-center gap-2 rounded-xl border border-border bg-white px-3 py-1.5 text-lg font-medium text-foreground hover:bg-accent"
                >
                  <ArrowLeft className="h-6 w-6" />
                  Müfredat Yönetimi'ne Dön
                </button>
                <div className="text-sm font-medium text-foreground">Property Ağacı</div>
                <div className="text-xs text-muted-foreground">{effective.length} property (kendi + miras)</div>
              </div>
              <div className="flex items-center gap-2">
                <div className="inline-flex overflow-hidden rounded-xl border border-border bg-card text-sm">
                  <button
                    type="button"
                    onClick={() => setSortOrder('created')}
                    className={`px-3 py-2 font-medium transition-colors ${sortOrder === 'created' ? 'bg-primary text-white' : 'text-foreground hover:bg-accent'}`}
                  >
                    Oluşturma tarihi
                  </button>
                  <button
                    type="button"
                    onClick={() => setSortOrder('alpha')}
                    className={`px-3 py-2 font-medium transition-colors ${sortOrder === 'alpha' ? 'bg-primary text-white' : 'text-foreground hover:bg-accent'}`}
                  >
                    Alfabetik
                  </button>
                </div>
                <button
                  type="button"
                  onClick={handleAddRoot}
                  disabled={busy}
                  className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
                  style={{ background: 'linear-gradient(to right, var(--primary), var(--secondary))' }}
                >
                  <Plus className="h-4 w-4" />
                  Yeni Kök Alan
                </button>
              </div>
            </div>
            <div className="p-4">
              <PropertyTreeView
                roots={propertyRoots}
                currentNodeId={currentNode.id}
                curriculumNodeNames={curriculumNodeNames}
                busy={busy}
                onAddChild={handleAddChild}
                onDelete={handleDelete}
              />
            </div>
          </div>
        )}

        {currentNode ? (
          <AddPropertyModal
            open={addModal.open}
            onClose={() => setAddModal({ open: false, parent: null })}
            parent={addModal.parent}
            currentNode={currentNode}
            onCreated={reload}
            setNotice={setNotice}
          />
        ) : null}
      </motion.div>
    </div>
  )
}
