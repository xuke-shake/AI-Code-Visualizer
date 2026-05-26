import type { DiagramDetail, DiagramType, ExportResult, GenerateDiagramPayload } from '@/types'
import { requestData } from './http'

type BackendDiagramType = 'flowchart' | 'sequence' | 'state' | 'architecture'

interface BackendAnalysisStart {
  task_id: number
  status: string
  diagram_id: number | null
}

interface BackendDiagram {
  id: number
  project_id: number
  creator_id: number
  title: string
  diagram_type: BackendDiagramType
  prompt?: string | null
  mermaid_code: string
  node_mapping_json?: Record<string, any> | null
  version: number
  is_outdated: boolean
  created_at: string
}

interface BackendExportOut {
  download_url: string
  object_key: string
  format: string
}

interface BackendShareOut {
  share_url: string
  share_token: string
  expires_at: string
}

function toBackendDiagramType(type: DiagramType): BackendDiagramType {
  if (type === 'sequenceDiagram') return 'sequence'
  if (type === 'stateDiagram') return 'state'
  if (type === 'classDiagram') return 'architecture'
  return 'flowchart'
}

function toFrontendDiagramType(type: BackendDiagramType): DiagramType {
  if (type === 'sequence') return 'sequenceDiagram'
  if (type === 'state') return 'stateDiagram'
  if (type === 'architecture') return 'classDiagram'
  return 'flowchart'
}

function toDiagramDetail(data: BackendDiagram): DiagramDetail {
  const sourceMap: DiagramDetail['sourceMap'] = {}

  Object.entries(data.node_mapping_json || {}).forEach(([label, value]) => {
    sourceMap[label] = {
      filePath: value.file_path || value.filePath || '',
      startLine: value.start_line || value.startLine || 1,
      endLine: value.end_line || value.endLine || 1,
      code: value.code || '',
    }
  })

  return {
    id: String(data.id),
    projectId: String(data.project_id),
    title: data.title,
    type: toFrontendDiagramType(data.diagram_type),
    mermaidCode: data.mermaid_code,
    version: data.version,
    outdated: data.is_outdated,
    updatedAt: data.created_at,
    sourceMap,
  }
}

export async function generateDiagramApi(
  projectId: string,
  payload: GenerateDiagramPayload,
): Promise<DiagramDetail> {
  const start = await requestData<BackendAnalysisStart>({
    url: `/api/projects/${projectId}/analysis`,
    method: 'post',
    data: {
      prompt: payload.instruction,
      diagram_type: toBackendDiagramType(payload.type),
      scope: payload.selectedPaths.join(','),
      title: payload.instruction.slice(0, 40) || '源码流程图',
      parameters: {
        selectedPaths: payload.selectedPaths,
      },
    },
  })

  if (!start.diagram_id) {
    throw new Error('后端未返回 diagram_id')
  }

  const diagram = await requestData<BackendDiagram>({
    url: `/api/diagrams/${start.diagram_id}`,
    method: 'get',
  })

  return toDiagramDetail(diagram)
}

export async function fetchDiagramApi(projectId: string): Promise<DiagramDetail | null> {
  const diagram = await requestData<BackendDiagram | null>({
    url: `/api/projects/${projectId}/diagram`,
    method: 'get',
  })

  return diagram ? toDiagramDetail(diagram) : null
}

export async function saveDiagramApi(
  _projectId: string,
  diagramId: string,
  payload: Partial<DiagramDetail>,
): Promise<DiagramDetail> {
  const data = await requestData<BackendDiagram>({
    url: `/api/diagrams/${diagramId}`,
    method: 'patch',
    data: {
      title: payload.title,
      mermaid_code: payload.mermaidCode,
    },
  })

  return toDiagramDetail(data)
}

export async function exportDiagramApi(
  _projectId: string,
  diagramId: string,
  type: string,
): Promise<ExportResult> {
  const data = await requestData<BackendExportOut>({
    url: `/api/diagrams/${diagramId}/export`,
    method: 'post',
    data: {
      format: type,
    },
  })

  return {
    fileName: data.object_key.split('/').pop() || `diagram.${type}`,
    mimeType: 'text/plain',
    content: data.download_url,
  }
}

export async function shareDiagramApi(
  _projectId: string,
  diagramId: string,
): Promise<{ shareUrl: string }> {
  const data = await requestData<BackendShareOut>({
    url: `/api/diagrams/${diagramId}/share`,
    method: 'post',
    data: {
      expire_hours: 72,
    },
  })

  const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

  return {
    shareUrl: `${base}${data.share_url}`,
  }
}