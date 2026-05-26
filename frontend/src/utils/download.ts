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

export async function downloadSvgAsPng(svgElement: SVGElement, fileName: string): Promise<void> {
  const serializer = new XMLSerializer()
  const svgMarkup = serializer.serializeToString(svgElement)
  const svgBlob = new Blob([svgMarkup], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(svgBlob)
  const image = new Image()

  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('PNG 导出失败'))
    image.src = url
  })

  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1200, image.width)
  canvas.height = Math.max(800, image.height)
  const context = canvas.getContext('2d')

  if (!context) {
    URL.revokeObjectURL(url)
    throw new Error('浏览器不支持 Canvas 导出')
  }

  context.fillStyle = '#02121f'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, 0, 0)

  await new Promise<void>((resolve) => {
    canvas.toBlob((blob) => {
      if (blob) {
        downloadBlob(blob, fileName)
      }
      resolve()
    }, 'image/png')
  })

  URL.revokeObjectURL(url)
}

export async function downloadSvgAsPdf(svgElement: SVGElement, fileName: string): Promise<void> {
  const serializer = new XMLSerializer()
  const svgMarkup = serializer.serializeToString(svgElement)
  const svgBlob = new Blob([svgMarkup], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(svgBlob)
  const image = new Image()

  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('PDF 导出失败'))
    image.src = url
  })

  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1200, image.width)
  canvas.height = Math.max(800, image.height)
  const context = canvas.getContext('2d')

  if (!context) {
    URL.revokeObjectURL(url)
    throw new Error('浏览器不支持 Canvas 导出')
  }

  context.fillStyle = '#02121f'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, 0, 0)

  const pdf = new jsPDF({
    orientation: canvas.width > canvas.height ? 'landscape' : 'portrait',
    unit: 'px',
    format: [canvas.width, canvas.height],
  })

  pdf.addImage(canvas.toDataURL('image/png'), 'PNG', 0, 0, canvas.width, canvas.height)
  pdf.save(fileName)
  URL.revokeObjectURL(url)
}
