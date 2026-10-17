import { AlertCircle, RotateCcw } from 'lucide-react'
import { Component, type ErrorInfo, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'

interface Props {
  children: ReactNode
  onReset?: () => void
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled UI error:', error, info)
  }

  reset = () => {
    this.setState({ hasError: false, error: null })
    this.props.onReset?.()
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
          <div className="flex size-12 items-center justify-center rounded-full bg-destructive/15 text-destructive">
            <AlertCircle className="size-6" />
          </div>
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">Đã xảy ra lỗi khi tải nội dung</h2>
            <p className="max-w-md text-sm text-muted-foreground">
              {this.state.error?.message || 'Có lỗi không mong muốn đã xảy ra trong quá trình hiển thị.'}
            </p>
          </div>
          <Button onClick={this.reset} variant="outline" className="gap-2">
            <RotateCcw className="size-4" />
            Thử lại
          </Button>
        </div>
      )
    }
    return this.props.children
  }
}

