
import { useEffect, useRef, useState, type FormEvent } from 'react'
import './App.css'

type DocumentItem = {
  id: string
  filename: string
  pages: number
  total_chunks: number
  uploaded_at: string
}

type Source = {
  chunk_index: number
  document_chunk_index?: number
  document_id: string
  filename: string
  page_number: number
  text: string
  score: number
}

type Message = {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
}

type AnswerResponse = {
  answer: string
  sources: Source[]
  model: string
  resolved_question?: string
}


const CHAT_STORAGE_KEY = 'enterprise-ai-current-chat'

type SavedChat = {
  selectedDocumentId: string | null
  messages: Message[]
}

function loadSavedChat(): SavedChat {
  const emptyChat: SavedChat = {
    selectedDocumentId: null,
    messages: [],
  }

  try {
    const stored = localStorage.getItem(CHAT_STORAGE_KEY)

    if (!stored) return emptyChat

    const parsed: unknown = JSON.parse(stored)

    if (!parsed || typeof parsed !== 'object') {
      return emptyChat
    }

    const chat = parsed as Partial<SavedChat>

    if (
      chat.selectedDocumentId !== null &&
      typeof chat.selectedDocumentId !== 'string'
    ) {
      return emptyChat
    }

    if (!Array.isArray(chat.messages)) {
      return emptyChat
    }

    const validMessages = chat.messages.every(
      (message) =>
        message &&
        typeof message === 'object' &&
        typeof message.id === 'number' &&
        (message.role === 'user' ||
          message.role === 'assistant') &&
        typeof message.content === 'string'
    )

    if (!validMessages) return emptyChat

    return {
      selectedDocumentId: chat.selectedDocumentId,
      messages: chat.messages,
    }
  } catch {
    return emptyChat
  }
}


let nextMessageId = 1

function App() {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  
  const [savedChat] = useState(loadSavedChat)

  const [selectedDocumentId, setSelectedDocumentId] =
    useState<string | null>(savedChat.selectedDocumentId)

  const [messages, setMessages] =
    useState<Message[]>(savedChat.messages)
    

  nextMessageId = Math.max(
    nextMessageId,
    ...savedChat.messages.map((message) => message.id + 1)
  )

  const [question, setQuestion] = useState('')

  const [uploading, setUploading] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [loadingDocuments, setLoadingDocuments] = useState(true)
  const [error, setError] = useState('')

  const fileInputRef = useRef<HTMLInputElement>(null)

  const selectedDocument = documents.find(
    (doc) => doc.id === selectedDocumentId
  )

  const busy = uploading || thinking || deletingId !== null


  useEffect(() => {
    try {
      localStorage.setItem(
        CHAT_STORAGE_KEY,
        JSON.stringify({
          selectedDocumentId,
          messages,
        })
      )
    } catch {
      // Storage may be unavailable or full.
      // The chat can still function in memory.
    }
  }, [selectedDocumentId, messages])


  async function readError(response: Response): Promise<string> {
    try {
      const data = await response.json()

      return typeof data.detail === 'string'
        ? data.detail
        : `Request failed (${response.status})`
    } catch {
      return `Request failed (${response.status})`
    }
  }

  async function fetchDocuments(): Promise<DocumentItem[]> {
    const response = await fetch('/api/documents', {
      cache: 'no-store',
    })

    if (!response.ok) {
      throw new Error(await readError(response))
    }

    const data: { documents: DocumentItem[] } =
      await response.json()

    return data.documents
  }

  // Load existing PostgreSQL documents when the page opens.
  useEffect(() => {
    let cancelled = false

    async function loadDocuments() {
      try {
        const results = await fetchDocuments()

        if (!cancelled) {
          setDocuments(results)
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : 'Could not load documents.'
          )
        }
      } finally {
        if (!cancelled) {
          setLoadingDocuments(false)
        }
      }
    }

    void loadDocuments()

    return () => {
      cancelled = true
    }
  }, [])

  // Switching documents clears conversation history.
  function selectDocument(id: string | null) {
    if (busy) return

    setSelectedDocumentId(id)
    setMessages([])
    setQuestion('')
    setError('')
  }

  async function uploadDocument(file: File) {
    if (busy) return

    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Please choose a PDF file.')
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

      const uploaded: DocumentItem = await response.json()

      // Immediately add the uploaded document to the sidebar.
      setDocuments((previous) => [
        uploaded,
        ...previous.filter((doc) => doc.id !== uploaded.id),
      ])

      setSelectedDocumentId(uploaded.id)
      setMessages([])
      setQuestion('')

      // Synchronize with the database.
      try {
        const updated = await fetchDocuments()
        setDocuments(updated)
      } catch {
        setError(
          'Document uploaded, but the library could not be refreshed.'
        )
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Document upload failed.'
      )

      try {
        const updated = await fetchDocuments()
        setDocuments(updated)
      } catch {
        // Preserve original error.
      }
    } finally {
      setUploading(false)

      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  // Delete from PostgreSQL and update the React sidebar.
  async function deleteDocument(doc: DocumentItem) {
    if (busy) return

    const confirmed = window.confirm(
      `Permanently delete "${doc.filename}" from the knowledge base?`
    )

    if (!confirmed) return

    setDeletingId(doc.id)
    setError('')

    try {
      const response = await fetch(
        `/api/documents/${encodeURIComponent(doc.id)}`,
        {
          method: 'DELETE',
        }
      )

      if (!response.ok) {
        // If the record is already gone, synchronize the UI.
        if (response.status === 404) {
          const updated = await fetchDocuments()
          setDocuments(updated)

          setMessages([])
          setQuestion('')

          if (
            !updated.some((item) => item.id === selectedDocumentId)
          ) {
            setSelectedDocumentId(null)
          }

          return
        }

        throw new Error(await readError(response))
      }

      // Remove the deleted document immediately.
      setDocuments((previous) =>
        previous.filter((item) => item.id !== doc.id)
      )

      // Clear potentially outdated answers and references.
      setMessages([])
      setQuestion('')

      if (selectedDocumentId === doc.id) {
        setSelectedDocumentId(null)
      }

      // Fetch the authoritative document list from PostgreSQL.
      try {
        const updated = await fetchDocuments()
        setDocuments(updated)

        if (
          selectedDocumentId !== null &&
          !updated.some((item) => item.id === selectedDocumentId)
        ) {
          setSelectedDocumentId(null)
        }
      } catch {
        setError(
          'Document deleted successfully, but refreshing the library failed.'
        )
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to delete document.'
      )

      // Attempt to recover the correct database state.
      try {
        const updated = await fetchDocuments()
        setDocuments(updated)
      } catch {
        // Keep the original error.
      }
    } finally {
      setDeletingId(null)
    }
  }

  async function askQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const text = question.trim()

    if (!text || documents.length === 0 || busy) return

    // CONVERSATION MEMORY:
    // Capture the last six completed messages BEFORE adding
    // the current question. This prevents duplicate messages
    // and allows the backend to resolve follow-up questions.
    const history = messages
      .filter((message) => message.content.trim())
      .slice(-6)
      .map(({ role, content }) => ({
        role,
        content: content.slice(0, 2000),
      }))

    setMessages((previous) => [
      ...previous,
      {
        id: nextMessageId++,
        role: 'user',
        content: text,
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
          question: text,
          top_k: 5,
          document_id: selectedDocumentId,
          history: history,
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
        err instanceof Error
          ? err.message
          : 'Could not generate an answer.'
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
            <div className="brand-subtitle">
              Knowledge Workspace
            </div>
          </div>
        </div>

        <button
          className="new-chat-button"
          disabled={busy}
          onClick={() => {
            setMessages([])
            setQuestion('')
            setError('')
          }}
        >
          ＋ New chat
        </button>

        <div className="sidebar-section">
          <div className="section-heading">
            WORKSPACE
          </div>

          <div className="sidebar-link active">
            ▤ &nbsp; AI Assistant
          </div>
        </div>

        <div className="sidebar-section">
          <div className="section-heading">
            KNOWLEDGE BASE
          </div>

          <button
            className={`document-filter ${
              selectedDocumentId === null ? 'selected' : ''
            }`}
            onClick={() => selectDocument(null)}
            disabled={busy}
          >
            <span>▦</span>
            <span>All documents</span>

            <span className="document-count">
              {documents.length}
            </span>
          </button>

          {loadingDocuments ? (
            <p className="sidebar-hint">
              Loading documents...
            </p>
          ) : documents.length === 0 ? (
            <p className="sidebar-hint">
              No documents uploaded yet
            </p>
          ) : (
            <div className="document-list">
              {documents.map((doc) => (
                <div
                  key={doc.id}
                  className={`library-document ${
                    selectedDocumentId === doc.id
                      ? 'selected'
                      : ''
                  }`}
                >
                  <button
                    className="library-document-select"
                    disabled={busy}
                    title={doc.filename}
                    onClick={() => selectDocument(doc.id)}
                  >
                    <span className="document-symbol">
                      ▧
                    </span>

                    <span className="document-info">
                      <span className="document-name">
                        {doc.filename}
                      </span>

                      <span className="document-meta">
                        {doc.pages} pages ·{' '}
                        {doc.total_chunks} chunks
                      </span>
                    </span>
                  </button>

                  <button
                    className="delete-document"
                    title={`Delete ${doc.filename}`}
                    aria-label={`Delete ${doc.filename}`}
                    disabled={busy}
                    onClick={() => void deleteDocument(doc)}
                  >
                    {deletingId === doc.id ? '…' : '×'}
                  </button>
                </div>
              ))}
            </div>
          )}

          <button
            className="upload-secondary"
            disabled={busy}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploading
              ? 'Uploading...'
              : '+ Upload document'}
          </button>
        </div>

        <div className="sidebar-footer">
          <span className="status-dot" />
          Local AI · Qwen2.5 3B
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <div className="topbar-title">
              AI Assistant
            </div>

            <div className="topbar-subtitle">
              {selectedDocument
                ? `Searching: ${selectedDocument.filename}`
                : `Searching all documents (${documents.length})`}
            </div>
          </div>

          <div className="model-pill">
            <span className="model-dot" />
            Qwen2.5 3B
          </div>
        </header>

        <div className="chat-content">
          {messages.length === 0 ? (
            <div className="welcome">
              <div className="welcome-icon">✦</div>

              <h1>
                Knowledge, at your fingertips.
              </h1>

              <p>
                Explore your knowledge base with
                AI-powered questions, semantic search,
                and document-backed answers.
              </p>

              <div className="welcome-actions">
                <button
                  className="primary-button"
                  disabled={busy}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {uploading
                    ? 'Processing...'
                    : '↑ Upload a PDF'}
                </button>
              </div>

              {documents.length > 0 && (
                <div className="ready-card">
                  <span className="ready-dot" />

                  <span>
                    <strong>
                      {selectedDocument
                        ? selectedDocument.filename
                        : `${documents.length} documents`}
                    </strong>{' '}
                    ready to search.
                  </span>
                </div>
              )}

              <div className="feature-grid">
                <div className="feature-card">
                  <div className="feature-icon">⌕</div>
                  <strong>Semantic search</strong>
                  <span>
                    Find relevant information
                    across documents.
                  </span>
                </div>

                <div className="feature-card">
                  <div className="feature-icon">✧</div>
                  <strong>AI-powered answers</strong>
                  <span>
                    Get responses using retrieved context.
                  </span>
                </div>

                <div className="feature-card">
                  <div className="feature-icon">▤</div>
                  <strong>Source references</strong>
                  <span>
                    See document names and page numbers.
                  </span>
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
                    {message.role === 'assistant'
                      ? '✦'
                      : 'U'}
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

                    {message.sources &&
                      message.sources.length > 0 && (
                        <details className="sources">
                          <summary>
                            View retrieved sources (
                            {message.sources.length})
                          </summary>

                          <div className="source-list">
                            {message.sources.map(
                              (source, index) => (
                                <div
                                  className="source-card"
                                  key={`${message.id}-${index}`}
                                >
                                  <div className="source-heading">
                                    <strong>
                                      Source{' '}
                                      {source.chunk_index + 1}
                                    </strong>

                                    <span>
                                      Similarity{' '}
                                      {source.score.toFixed(3)}
                                    </span>
                                  </div>

                                  <div className="source-location">
                                    ▧ {source.filename} ·
                                    Page {source.page_number}
                                  </div>

                                  <p>{source.text}</p>
                                </div>
                              )
                            )}
                          </div>
                        </details>
                      )}
                  </div>
                </div>
              ))}

              {thinking && (
                <div className="message assistant">
                  <div className="message-avatar">
                    ✦
                  </div>

                  <div className="message-body">
                    <div className="message-author">
                      Enterprise AI
                    </div>

                    <div className="thinking-message">
                      <span className="loader" />
                      Searching documents and
                      generating an answer...
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="composer-area">
          {error && (
            <div className="error-banner">
              {error}
            </div>
          )}

          <form
            className="composer"
            onSubmit={askQuestion}
          >
            <input
              value={question}
              onChange={(event) =>
                setQuestion(event.target.value)
              }
              disabled={
                documents.length === 0 || busy
              }
              placeholder={
                documents.length
                  ? 'Ask a question about your documents...'
                  : 'Upload a PDF to get started...'
              }
            />

            <button
              type="submit"
              className="send-button"
              disabled={
                !question.trim() ||
                documents.length === 0 ||
                busy
              }
              aria-label="Send question"
            >
              ↑
            </button>
          </form>

          <div className="composer-caption">
            Powered by local AI · Verify important
            answers against sources
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

          if (file) {
            void uploadDocument(file)
          }
        }}
      />
    </div>
  )
}

export default App
