
import { useRef, useState, type FormEvent } from 'react'
import './App.css'

type Source = {
  chunk_index: number
  text: string
  score: number
}

type Message = {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
}

type UploadResponse = {
  filename: string
  pages: number
  total_chunks: number
}

type AnswerResponse = {
  answer: string
  sources: Source[]
  model: string
}

let nextMessageId = 1

function App() {
  const [document, setDocument] = useState<UploadResponse | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [question, setQuestion] = useState('')
  const [uploading, setUploading] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [error, setError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function readError(response: Response) {
    try {
      const data = await response.json()
      return typeof data.detail === 'string'
        ? data.detail
        : `Request failed (${response.status})`
    } catch {
      return `Request failed (${response.status})`
    }
  }

  async function uploadDocument(file: File) {
    if (uploading || thinking) return

    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Please select a PDF document.')
      return
    }

    if (file.size > 10 * 1024 * 1024) {
      setError('PDF must be 10 MB or smaller.')
      return
    }

    setUploading(true)
    setError('')

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch('/api/documents/upload', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        throw new Error(await readError(response))
      }

      const data: UploadResponse = await response.json()

      setDocument(data)
      setMessages([])
      setQuestion('')
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to upload document.'
      )
    } finally {
      setUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  async function askQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const trimmedQuestion = question.trim()

    if (!trimmedQuestion || !document || thinking || uploading) return

    setMessages((previous) => [
      ...previous,
      {
        id: nextMessageId++,
        role: 'user',
        content: trimmedQuestion,
      },
    ])

    setQuestion('')
    setThinking(true)
    setError('')

    try {
      const response = await fetch('/api/documents/ask', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question: trimmedQuestion,
          top_k: 3,
        }),
      })

      if (!response.ok) {
        throw new Error(await readError(response))
      }

      const data: AnswerResponse = await response.json()

      setMessages((previous) => [
        ...previous,
        {
          id: nextMessageId++,
          role: 'assistant',
          content: data.answer,
          sources: data.sources,
        },
      ])
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to generate an answer.'
      )
    } finally {
      setThinking(false)
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">✦</div>
          <div>
            <div className="brand-name">Enterprise AI</div>
            <div className="brand-subtitle">Knowledge Workspace</div>
          </div>
        </div>

        <button
          className="new-chat-button"
          onClick={() => {
            setMessages([])
            setError('')
          }}
        >
          <span>＋</span> New chat
        </button>

        <div className="sidebar-section">
          <div className="section-heading">WORKSPACE</div>

          <div className="sidebar-link active">
            <span>▤</span> AI Assistant
          </div>
        </div>

        <div className="sidebar-section">
          <div className="section-heading">KNOWLEDGE BASE</div>

          {document ? (
            <div className="document-item">
              <span className="document-symbol">▧</span>
              <div className="document-info">
                <div className="document-name">{document.filename}</div>
                <div className="document-meta">
                  {document.pages} pages · {document.total_chunks} chunks
                </div>
              </div>
            </div>
          ) : (
            <p className="sidebar-hint">No documents uploaded</p>
          )}

          <button
            className="upload-secondary"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || thinking}
          >
            {uploading ? 'Uploading...' : '+ Upload document'}
          </button>
        </div>

        <div className="sidebar-footer">
          <div className="status-dot" />
          <span>Local AI · Qwen3 4B</span>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <div className="topbar-title">AI Assistant</div>
            <div className="topbar-subtitle">
              Ask questions grounded in your documents
            </div>
          </div>
          <div className="model-pill">
            <span className="model-dot" />
            Qwen3 4B
          </div>
        </header>

        <div className="chat-content">
          {messages.length === 0 ? (
            <div className="welcome">
              <div className="welcome-icon">✦</div>
              <h1>Knowledge, at your fingertips.</h1>
              <p>
                Upload a document and get AI-powered answers
                grounded in your own information.
              </p>

              <div className="welcome-actions">
                <button
                  className="primary-button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading || thinking}
                >
                  {uploading ? 'Processing...' : '↑ Upload a PDF'}
                </button>
              </div>

              {document && (
                <div className="ready-card">
                  <span className="ready-dot" />
                  <span>
                    <strong>{document.filename}</strong> is ready.
                    Ask a question below.
                  </span>
                </div>
              )}

              <div className="feature-grid">
                <div className="feature-card">
                  <div className="feature-icon">⌕</div>
                  <strong>Semantic search</strong>
                  <span>Find information beyond keyword matching.</span>
                </div>

                <div className="feature-card">
                  <div className="feature-icon">✧</div>
                  <strong>AI-powered answers</strong>
                  <span>Generate responses based on document context.</span>
                </div>

                <div className="feature-card">
                  <div className="feature-icon">▤</div>
                  <strong>Source references</strong>
                  <span>Inspect the retrieved excerpts behind an answer.</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="messages">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`message ${message.role}`}
                >
                  <div className="message-avatar">
                    {message.role === 'assistant' ? '✦' : 'U'}
                  </div>

                  <div className="message-body">
                    <div className="message-author">
                      {message.role === 'assistant'
                        ? 'Enterprise AI'
                        : 'You'}
                    </div>

                    <div className="message-text">
                      {message.content}
                    </div>

                    {message.sources && message.sources.length > 0 && (
                      <details className="sources">
                        <summary>
                          View retrieved sources ({message.sources.length})
                        </summary>

                        <div className="source-list">
                          {message.sources.map((source) => (
                            <div
                              className="source-card"
                              key={source.chunk_index}
                            >
                              <div className="source-heading">
                                <strong>
                                  Source {source.chunk_index + 1}
                                </strong>
                                <span>
                                  Similarity {source.score.toFixed(3)}
                                </span>
                              </div>
                              <p>{source.text}</p>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                </div>
              ))}

              {thinking && (
                <div className="message assistant">
                  <div className="message-avatar">✦</div>
                  <div className="message-body">
                    <div className="message-author">Enterprise AI</div>
                    <div className="thinking-message">
                      <span className="loader" />
                      Analyzing your document...
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="composer-area">
          {error && <div className="error-banner">{error}</div>}

          <form className="composer" onSubmit={askQuestion}>
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={
                document
                  ? 'Ask a question about your document...'
                  : 'Upload a PDF to start asking questions...'
              }
              disabled={!document || thinking || uploading}
            />

            <button
              className="send-button"
              type="submit"
              disabled={!document || !question.trim() || thinking || uploading}
              aria-label="Send question"
            >
              ↑
            </button>
          </form>

          <div className="composer-caption">
            Powered by local AI · Verify important information against sources
          </div>
        </div>
      </main>

      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,application/pdf"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) void uploadDocument(file)
        }}
      />
    </div>
  )
}

export default App
