import { useEffect, useMemo, useState } from 'react'
import { motion } from 'motion/react'
import { Play, RefreshCw, FileCode, Hash } from 'lucide-react'

import { AgentRunsPanel } from '../components/AgentRunsPanel'
import { HtmlIterationsPanel } from '../components/HtmlIterationsPanel'
import { HtmlLayoutEditor } from '../components/HtmlLayoutEditor'
import { HtmlViewer } from '../components/HtmlViewer'
import { Modal } from '../components/Modal'
import { JsonPanel } from '../components/JsonPanel'
import { LogStreamPanel } from '../components/LogStreamPanel'
import { PipelineLogsPanel } from '../components/PipelineLogsPanel'
import { StatusBadge } from '../components/StatusBadge'
import { YamlInstanceCascadeSelector } from '../components/YamlInstanceCascadeSelector'
import { useLogStream } from '../hooks/useLogStream'
import { usePolling } from '../hooks/usePolling'
import { ApiError, api } from '../lib/api'
import { pickHtmlContent } from '../lib/html'
import { randomUuid } from '../lib/uuid'
import type {
  CurriculumNodeItem,
  FullPipelineRunResponse,
  PipelineAgentLinkResponse,
  PipelineGetResponse,
  PipelineLogEntryResponse,
  RetryConfig,
  YamlInstanceItem,
  YamlTemplateItem,
} from '../types'

const EMPTY_RETRY: RetryConfig = {
  question_max_retries: 3,
  layout_max_retries: 3,
  html_max_retries: 3,
  image_max_retries: 2,
  rule_eval_parallelism: 4,
}

function toRetryConfig(input: RetryConfig): RetryConfig {
  const output: Record<string, number> = {}
  for (const [key, raw] of Object.entries(input)) {
    const value = Number(raw)
    if (Number.isFinite(value) && value > 0) {
      output[key] = value
    }
  }
  return output as RetryConfig
}

export function FullPipelinePage() {
  const [curriculumTree, setCurriculumTree] = useState<CurriculumNodeItem[]>([])
  const [yamlTemplates, setYamlTemplates] = useState<YamlTemplateItem[]>([])
  const [yamlInstances, setYamlInstances] = useState<YamlInstanceItem[]>([])
  const [yamlInstanceId, setYamlInstanceId] = useState('')
  const [retryConfig, setRetryConfig] = useState<RetryConfig>(EMPTY_RETRY)

  const [running, setRunning] = useState(false)
  const [reRendering, setReRendering] = useState(false)
  const [error, setError] = useState('')
  const { lines, connected, done, active, renders, validations, connect } = useLogStream()

  const [response, setResponse] = useState<FullPipelineRunResponse | null>(null)
  const [pipeline, setPipeline] = useState<PipelineGetResponse | null>(null)
  const [pipelineRuns, setPipelineRuns] = useState<PipelineAgentLinkResponse[]>([])
  const [pipelineLogs, setPipelineLogs] = useState<PipelineLogEntryResponse[]>([])

  useEffect(() => {
    void (async () => {
      try {
        const [tree, templates, items] = await Promise.all([
          api.getCurriculumTree(),
          api.listYamlTemplates(),
          api.listYamlInstances(),
        ])
        setCurriculumTree(tree)
        setYamlTemplates(templates)
        setYamlInstances(items)
        if (!yamlInstanceId && items.length > 0) {
          setYamlInstanceId(items[0].id)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'YAML instance listesi alınamadı')
      }
    })()
  }, [])

  const refreshAll = async (snapshot?: FullPipelineRunResponse | null): Promise<void> => {
    const source = snapshot ?? response
    if (!source) return

    const pipelineId = source.pipeline_id

    const [pipelineData, links, logs] = await Promise.all([
      api.getPipeline(pipelineId),
      api.getPipelineAgentRuns(pipelineId),
      api.getPipelineLogs(pipelineId),
    ])

    setPipeline(pipelineData)
    setPipelineRuns(links)
    setPipelineLogs(logs)
  }

  usePolling(
    () => refreshAll(),
    Boolean(response?.pipeline_id) && (pipeline?.status ?? 'running') === 'running',
    2500,
  )

  useEffect(() => {
    if (!response) return
    void refreshAll(response).catch((e) => {
      setError(e instanceof Error ? e.message : 'Pipeline durumu yenilenemedi')
    })
  }, [response?.pipeline_id])

  const run = async () => {
    if (!yamlInstanceId) {
      setError('YAML instance seçilmedi.')
      return
    }
    setRunning(true)
    setError('')
    const key = randomUuid()
    connect(key)
    try {
      const result = await api.runFullPipeline({
        yaml_instance_id: yamlInstanceId,
        retry_config: toRetryConfig(retryConfig),
        stream_key: key,
      })
      setResponse(result)
      await refreshAll(result)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Pipeline çalıştırılırken beklenmeyen bir hata oluştu.')
    } finally {
      setRunning(false)
    }
  }

  const [htmlOverrideMain, setHtmlOverrideMain] = useState<string | null>(null)
  const [renderedImageOverrideArtifactId, setRenderedImageOverrideArtifactId] = useState<string | null>(null)
  const [editorOpenMain, setEditorOpenMain] = useState(false)

  const rawHtmlFromResponse = useMemo(() => pickHtmlContent(response?.question_html), [response])
  const htmlFromResponse = htmlOverrideMain ?? rawHtmlFromResponse
  const fullRenderedImageArtifactId = renderedImageOverrideArtifactId ?? response?.rendered_image_artifact_id ?? ''
  const fullRenderedImageUrl = useMemo(() => {
    if (!fullRenderedImageArtifactId) return ''
    return `/v1/assets/${encodeURIComponent(fullRenderedImageArtifactId)}`
  }, [fullRenderedImageArtifactId])

  useEffect(() => {
    setRenderedImageOverrideArtifactId(null)
    setHtmlOverrideMain(null)
  }, [response?.pipeline_id])

  const handleSaveEditedHtml = async (editedHtml: string) => {
    setHtmlOverrideMain(editedHtml)
    setEditorOpenMain(false)
    setReRendering(true)
    try {
      const rendered = await api.reRenderHtmlAsset({
        html_content: editedHtml,
        pipeline_id: response?.pipeline_id,
      })
      setRenderedImageOverrideArtifactId(rendered.rendered_image_artifact_id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'HTML kaydedildi ancak PNG yeniden render edilemedi.')
    } finally {
      setReRendering(false)
    }
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="space-y-6"
      >
        {/* Page Header */}
        <div>
          <h1 className="text-3xl mb-1" style={{ fontFamily: 'var(--font-display)' }}>
            Full Pipeline
          </h1>
          <p className="text-muted-foreground">YAML'dan HTML çıktısına kadar uçtan uca pipeline</p>
        </div>

        {/* Configuration Card */}
        <div className="bg-card rounded-2xl shadow-xl border border-border overflow-hidden">
          <div className="px-8 py-5 border-b border-border"
            style={{ background: 'linear-gradient(to right, var(--accent), var(--muted))' }}>
            <h2 className="text-xl" style={{ fontFamily: 'var(--font-display)' }}>
              Pipeline Yapılandırması
            </h2>
          </div>

          <div className="p-8 space-y-6">
            {/* YAML File */}
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                <FileCode className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                <span>YAML Instance</span>
              </div>
              <YamlInstanceCascadeSelector
                curriculumTree={curriculumTree}
                templates={yamlTemplates}
                instances={yamlInstances}
                value={yamlInstanceId}
                onChange={setYamlInstanceId}
                selectClassName="w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none transition-colors"
                inputClassName="w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none transition-colors"
              />
            </div>

            {/* Retry Grid */}
            <div className="grid grid-cols-3 gap-5">
              {(
                [
                  { key: 'question_max_retries', label: 'Question Yeniden Deneme' },
                  { key: 'layout_max_retries', label: 'Layout Yeniden Deneme' },
                  { key: 'html_max_retries', label: 'HTML Yeniden Deneme' },
                ] as const
              ).map(({ key, label }) => (
                <div key={key} className="space-y-2">
                  <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <Hash className="w-4 h-4" style={{ color: 'var(--primary)' }} />
                    {label}
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={retryConfig[key] ?? 3}
                    onChange={(e) => setRetryConfig((prev) => ({ ...prev, [key]: Number(e.target.value) }))}
                    className="w-full px-4 py-3 rounded-xl border-2 bg-white focus:outline-none transition-colors text-center"
                    style={{ borderColor: 'var(--border)' }}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Footer Actions */}
          <div className="px-8 py-5 border-t border-border flex gap-3 bg-muted/20">
            <button
              type="button"
              onClick={() => void run()}
              disabled={running}
              className="flex items-center gap-2 px-6 py-3 rounded-xl text-white font-medium shadow-lg hover:shadow-xl hover:scale-[1.02] transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
              style={{ background: `linear-gradient(to right, var(--primary), var(--secondary))` }}
            >
              <Play className="w-4 h-4" fill="currentColor" />
              {running ? 'Çalışıyor...' : 'Full Pipeline Çalıştır'}
            </button>
            <button
              type="button"
              onClick={() => void refreshAll()}
              disabled={!response}
              className="flex items-center gap-2 px-6 py-3 rounded-xl border-2 font-medium hover:bg-accent transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ borderColor: 'var(--border)', color: 'var(--foreground)' }}
            >
              <RefreshCw className="w-4 h-4" />
              Şimdi Yenile
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="px-5 py-4 rounded-xl border text-sm bg-red-50 border-red-200 text-red-700">
            {error}
          </div>
        )}

        {/* HTML Iterations (real-time, visible even before pipeline finishes) */}
        <HtmlIterationsPanel renders={renders} validations={validations} running={running} />

        {/* Results Section */}
        {response && (
          <div className="space-y-4">
            {/* Pipeline Status */}
            <div className="bg-card rounded-2xl border border-border p-6">
              <h3 className="text-lg font-medium mb-3" style={{ fontFamily: 'var(--font-display)' }}>
                Pipeline Özeti
              </h3>
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-3">
                  <span className="text-muted-foreground w-28 shrink-0">pipeline_id</span>
                  <code className="text-xs bg-muted px-2 py-1 rounded-lg truncate">{response.pipeline_id}</code>
                </div>
                {pipeline && (
                  <div className="flex items-center gap-3">
                    <span className="text-muted-foreground w-28 shrink-0">Durum</span>
                    <StatusBadge status={pipeline.status} />
                  </div>
                )}
                {pipeline?.yaml_instance_id && (
                  <div className="flex items-center gap-3">
                    <span className="text-muted-foreground w-28 shrink-0">yaml_instance_id</span>
                    <code className="text-xs bg-muted px-2 py-1 rounded-lg truncate">{pipeline.yaml_instance_id}</code>
                  </div>
                )}
              </div>
            </div>

            {/* JSON Outputs */}
            <JsonPanel title="Question JSON" data={response.question_json} />
            <JsonPanel title="Layout Plan JSON" data={response.layout_plan_json} />

            {/* HTML Output */}
            {htmlFromResponse && (
              <>
                <HtmlViewer title="Full Pipeline HTML" html={htmlFromResponse} onEditClick={() => setEditorOpenMain(true)} />
                <Modal open={editorOpenMain} onClose={() => setEditorOpenMain(false)} size="full" title="HTML Layout Düzenleyici">
                  <HtmlLayoutEditor
                    html={htmlFromResponse}
                    onSave={(edited) => { void handleSaveEditedHtml(edited) }}
                    onCancel={() => setEditorOpenMain(false)}
                  />
                </Modal>
              </>
            )}

            {/* Rendered Image */}
            {fullRenderedImageUrl && (
              <div className="bg-card rounded-xl border border-border p-5">
                <h3 className="text-sm font-medium text-foreground mb-3">
                  Full Pipeline Nihai Render PNG {reRendering ? '(yeniden render ediliyor...)' : ''}
                </h3>
                <img
                  src={fullRenderedImageUrl}
                  alt="Full pipeline nihai render"
                  className="w-full rounded-lg border border-border"
                  style={{ maxWidth: 960 }}
                />
              </div>
            )}

            {/* Pipeline Logs & Agent Runs */}
            <PipelineLogsPanel title="Pipeline Event Logları" logs={pipelineLogs} onRefresh={refreshAll} />
            <AgentRunsPanel title="Pipeline Agent Run'ları" links={pipelineRuns} onRefresh={refreshAll} />
          </div>
        )}
        <LogStreamPanel lines={lines} connected={connected} done={done} title="Full Pipeline Logları" active={active} />
      </motion.div>
    </div>
  )
}
