import { jsPDF } from 'jspdf'

export function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.click()
  URL.revokeObjectURL(url)
}

export function downloadText(content: string, fileName: string, mimeType = 'text/plain'): void {
  downloadBlob(new Blob([content], { type: mimeType }), fileName)
}

const MAX_EXPORT_EDGE = 8192
const MAX_EXPORT_PIXELS = 16_000_000

function prepareSvg(svgElement: SVGElement): { svg: SVGElement; width: number; height: number } {
  const svg = svgElement.cloneNode(true) as SVGElement
  const viewBox = svg.getAttribute('viewBox')?.trim().split(/\s+/).map(Number)
  const rawWidth = viewBox?.length === 4 ? viewBox[2] : Number(svg.getAttribute('width'))
  const rawHeight = viewBox?.length === 4 ? viewBox[3] : Number(svg.getAttribute('height'))
  if (!Number.isFinite(rawWidth) || !Number.isFinite(rawHeight) || !(rawWidth > 0 && rawHeight > 0)) {
    throw new Error('导出失败：SVG 尺寸无效')
  }
  const ratio = Math.min(1, MAX_EXPORT_EDGE / rawWidth, MAX_EXPORT_EDGE / rawHeight, Math.sqrt(MAX_EXPORT_PIXELS / (rawWidth * rawHeight)))
  const width = Math.max(1, Math.floor(rawWidth * ratio))
  const height = Math.max(1, Math.floor(rawHeight * ratio))
  svg.setAttribute('width', String(width))
  svg.setAttribute('height', String(height))
  svg.style.width = `${width}px`
  svg.style.height = `${height}px`
  return { svg, width, height }
}

export async function downloadSvgAsPng(svgElement: SVGElement, fileName: string): Promise<void> {
  const serializer = new XMLSerializer()
  const prepared = prepareSvg(svgElement)
  const svgMarkup = serializer.serializeToString(prepared.svg)
  const svgBlob = new Blob([svgMarkup], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(svgBlob)
  const image = new Image()

  try {
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve()
      image.onerror = () => reject(new Error('PNG 导出失败：当前 SVG 无法转换为图片'))
      image.src = url
    })

  const canvas = document.createElement('canvas')
  canvas.width = prepared.width
  canvas.height = prepared.height
  const context = canvas.getContext('2d')

    if (!context) throw new Error('浏览器不支持 Canvas 导出')

  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, 0, 0)

    await new Promise<void>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        downloadBlob(blob, fileName)
        resolve()
      } else {
        reject(new Error('PNG 导出失败：浏览器未生成图片数据'))
      }
    }, 'image/png')
    })
  } finally {
    URL.revokeObjectURL(url)
  }
}

export async function downloadSvgAsPdf(svgElement: SVGElement, fileName: string): Promise<void> {
  const serializer = new XMLSerializer()
  const prepared = prepareSvg(svgElement)
  const svgMarkup = serializer.serializeToString(prepared.svg)
  const svgBlob = new Blob([svgMarkup], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(svgBlob)
  const image = new Image()

  try {
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve()
      image.onerror = () => reject(new Error('PDF 导出失败：当前 SVG 无法转换为图片'))
      image.src = url
    })

  const canvas = document.createElement('canvas')
  canvas.width = prepared.width
  canvas.height = prepared.height
  const context = canvas.getContext('2d')

    if (!context) throw new Error('浏览器不支持 Canvas 导出')

  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, 0, 0)

  const imageData = canvas.toDataURL('image/png')
  if (!imageData.startsWith('data:image/png')) throw new Error('PDF 导出失败：浏览器未生成 PNG 数据')
  const pdf = new jsPDF({
    orientation: canvas.width > canvas.height ? 'landscape' : 'portrait',
    unit: 'px',
    format: [canvas.width, canvas.height],
  })

  pdf.addImage(imageData, 'PNG', 0, 0, canvas.width, canvas.height)
    pdf.save(fileName)
  } finally {
    URL.revokeObjectURL(url)
  }
}
