import ReactDiffViewer, { DiffMethod } from 'react-diff-viewer-continued'

import { cn } from '@/lib/utils'

// Colors come from our status tokens, which already switch with the theme.
const mix = (token: string, percent: number) => `color-mix(in oklch, var(${token}) ${percent}%, transparent)`
const variables = {
  diffViewerBackground: 'transparent',
  diffViewerColor: 'var(--foreground)',
  addedBackground: mix('--status-accepted', 10),
  addedColor: 'var(--foreground)',
  wordAddedBackground: mix('--status-accepted', 32),
  removedBackground: mix('--status-rejected', 8),
  removedColor: 'var(--foreground)',
  wordRemovedBackground: mix('--status-rejected', 28),
  gutterBackground: 'transparent',
  addedGutterBackground: 'transparent',
  removedGutterBackground: 'transparent',
  addedGutterColor: 'var(--status-accepted-fg)',
  removedGutterColor: 'var(--status-rejected-fg)',
}

const styles = {
  variables: { light: variables, dark: variables },
  contentText: {
    fontFamily: 'inherit',
    fontSize: '0.875rem',
    lineHeight: 1.6,
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-word' as const,
  },
  marker: { fontFamily: 'inherit', paddingLeft: 8, paddingRight: 4 },
  line: { verticalAlign: 'top' },
}

// The viewer is built for code (fixed table width, flex rows, line-break: anywhere). Make it wrap like prose.
const proseLayout =
  'overflow-hidden rounded-md border py-1 [&_table]:w-full! [&_table]:min-w-0! [&_table]:table-fixed ' +
  '[&_td:first-child]:w-6 [&_[class*=content-flex]]:block! [&_[class*=content-text]]:w-auto! [&_[class*=content-text]_*]:[line-break:auto]! [&_[class*=content-text]]:[overflow-wrap:break-word]'

/** Word-level diff of an original passage against its proposed replacement. */
export function TextDiff({ oldValue, newValue, className }: { oldValue: string; newValue: string; className?: string }) {
  return (
    <div className={cn(proseLayout, className)}>
      <ReactDiffViewer
        oldValue={oldValue}
        newValue={newValue}
        splitView={false}
        hideLineNumbers
        hideSummary
        showDiffOnly={false}
        compareMethod={DiffMethod.WORDS}
        styles={styles}
      />
    </div>
  )
}
