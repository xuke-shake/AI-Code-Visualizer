import type { FileTreeNode } from '@/types'

export function collectLeafPaths(nodes: FileTreeNode[]): string[] {
  const result: string[] = []

  const walk = (items: FileTreeNode[]) => {
    items.forEach((item) => {
      if (item.type === 'file') {
        result.push(item.path)
        return
      }

      if (item.children?.length) {
        walk(item.children)
      }
    })
  }

  walk(nodes)
  return result
}

export function flattenTree(nodes: FileTreeNode[]): FileTreeNode[] {
  return nodes.flatMap((node) => [node, ...(node.children ? flattenTree(node.children) : [])])
}
