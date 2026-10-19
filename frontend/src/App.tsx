
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
const CHATS_STORAGE_KEY = 'enterprise-ai-saved-chats-v1'

type SavedChat = {
  id: string
  title: string
  selectedDocumentId: string | null
  messages: Message[]
  updatedAt: number
}

type ChatStore = {
  activeChatId: string
  chats: SavedChat[]
}

function makeChat(documentId: string | null = null): SavedChat {
  return {
    id: crypto.randomUUID(),
    title: 'New chat',
    selectedDocumentId: documentId,
    messages: [],
    updatedAt: Date.now(),
  }
}

function validMessages(value: unknown): value is Message[] {
  return Array.isArray(value) && value.every((item) =>
    item !== null &&
    typeof item === 'object' &&
    typeof item.id === 'number' &&
    (item.role === 'user' || item.role === 'assistant') &&
    typeof item.content === 'string'
  )
}

function loadChats(): ChatStore {
  try {
    const stored = localStorage.getItem(CHATS_STORAGE_KEY)

    if (stored) {
      const parsed: unknown = JSON.parse(stored)

      if (parsed && typeof parsed === 'object') {
        const data = parsed as Partial<ChatStore>

        if (Array.isArray(data.chats)) {
          const chats = data.chats.filter(
            (chat): chat is SavedChat =>
              chat !== null &&
              typeof chat === 'object' &&
              typeof chat.id === 'string' &&
              typeof chat.title === 'string' &&
              (chat.selectedDocumentId === null ||
                typeof chat.selectedDocumentId === 'string') &&
              validMessages(chat.messages) &&
              typeof chat.updatedAt === 'number'
          )

          if (chats.length > 0) {
            return {
              chats,
              activeChatId: chats.some(
                (chat) => chat.id === data.activeChatId
              )
                ? data.activeChatId as string
                : chats[0].id,
            }
          }
        }
      }
    }

    // Import previous single-chat history.
    const previous = localStorage.getItem(CHAT_STORAGE_KEY)

    if (previous) {
      const old = JSON.parse(previous) as {
        selectedDocumentId?: unknown
        messages?: unknown
      }

      if (
        validMessages(old.messages) &&
        (old.selectedDocumentId === null ||
          typeof old.selectedDocumentId === 'string')
      ) {
        const chat = makeChat(old.selectedDocumentId)

        chat.messages = old.messages
        chat.title = old.messages.find(
          (msg) => msg.role === 'user'
        )?.content.slice(0, 48) || 'New chat'

        return {
          activeChatId: chat.id,
          chats: [chat],
        }
      }
    }
  } catch {
    // Use a new chat if storage cannot be read.
  }

  const chat = makeChat()

  return {
    activeChatId: chat.id,
    chats: [chat],
  }
}

let nextMessageId = 1

function App() {
  const [documents, setDocuments] = useState<DocumentItem[]>([])

  const [initialStore] = useState(loadChats)

  const [chats, setChats] = useState<SavedChat[]>(
    initialStore.chats
  )

  const [activeChatId, setActiveChatId] = useState(
    initialStore.activeChatId
  )

  const initialChat = initialStore.chats.find(
    (chat) => chat.id === initialStore.activeChatId
  ) ?? initialStore.chats[0]

  const [selectedDocumentId, setSelectedDocumentId] =
    useState<string | null>(initialChat.selectedDocumentId)

  const [messages, setMessages] = useState<Message[]>(
    initialChat.messages
  )

  nextMessageId = Math.max(
    nextMessageId,
    ...initialStore.chats.flatMap((chat) =>
      chat.messages.map((message) => message.id + 1)
    )
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

  // Update the saved version of the current chat.
  useEffect(() => {
    setChats((previous) =>
      previous.map((chat) => {
        if (chat.id !== activeChatId) return chat

        const unchanged =
          chat.selectedDocumentId === selectedDocumentId &&
          chat.messages === messages

        if (unchanged) return chat

        const firstQuestion = messages.find(
          (item) => item.role === 'user'
        )

        return {
          ...chat,
          selectedDocumentId,
          messages,
          title:
            chat.title === 'New chat' && firstQuestion
              ? firstQuestion.content.slice(0, 48)
              : chat.title,
          updatedAt: Date.now(),
        }
      })
    )
  }, [activeChatId, selectedDocumentId, messages])

  // Save all conversations to browser storage.
  useEffect(() => {
    try {
      localStorage.setItem(
        CHATS_STORAGE_KEY,
        JSON.stringify({
          activeChatId,
          chats,
        })
      )
    } catch {
      // Chat continues even if storage is unavailable.
    }
  }, [activeChatId, chats])

  // Open an existing conversation.
  function openChat(chat: SavedChat) {
    if (busy || chat.id === activeChatId) return

    setActiveChatId(chat.id)
    setSelectedDocumentId(chat.selectedDocumentId)
    setMessages(chat.messages)
    setQuestion('')
    setError('')
  }

  // Create a new, separate conversation.
  function createChat(documentId: string | null = null) {
    if (busy) return

    const chat = makeChat(documentId)

    setChats((previous) => [chat, ...previous])
    setActiveChatId(chat.id)
    setSelectedDocumentId(documentId)
    setMessages(chat.messages)
    setQuestion('')
    setError('')
  }

  // Rename a conversation.
  function renameChat(chat: SavedChat) {
    if (busy) return

    const proposed = window.prompt(
      'Rename chat:',
      chat.title
    )

    if (proposed === null || !proposed.trim()) return

    setChats((previous) =>
      previous.map((item) =>
        item.id === chat.id
          ? {
              ...item,
              title: proposed.trim().slice(0, 80),
            }
          : item
      )
    )
  }

  // Delete one conversation without deleting documents.
  function removeChat(chat: SavedChat) {
    if (busy) return

    const confirmed = window.confirm(
      `Delete chat "${chat.title}"?`
    )

    if (!confirmed) return

    const remaining = chats.filter(
      (item) => item.id !== chat.id
    )

    // Deleting an inactive chat does not affect the open chat.
    if (chat.id !== activeChatId) {
      setChats(remaining)
      return
    }

    // Switch to another chat or create an empty one.
    const fallback = remaining[0] ?? makeChat()

    setChats(remaining.length ? remaining : [fallback])
    setActiveChatId(fallback.id)
    setSelectedDocumentId(fallback.selectedDocumentId)
    setMessages(fallback.messages)
    setQuestion('')
    setError('')
  }

  async function readError(
    response: Response
  ): Promise<string> {
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

  // Load documents from PostgreSQL.
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

  // Selecting a document starts a new chat for that document.
  function selectDocument(id: string | null) {
    if (busy) return

    createChat(id)
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

      setDocuments((previous) => [
        uploaded,
        ...previous.filter((doc) => doc.id !== uploaded.id),
      ])

      // Start a new chat for the uploaded document.
      // Existing chats are preserved.
      const uploadedChat = makeChat(uploaded.id)

      setChats((previous) => [
        uploadedChat,
        ...previous,
      ])

      setActiveChatId(uploadedChat.id)
      setSelectedDocumentId(uploaded.id)
      setMessages([])
      setQuestion('')

      // Refresh the document library.
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
        if (response.status === 404) {
          const updated = await fetchDocuments()
          setDocuments(updated)

          if (
            !updated.some(
              (item) => item.id === selectedDocumentId
            )
          ) {
            setSelectedDocumentId(null)
            setMessages([])
            setQuestion('')
          }

          return
        }

        throw new Error(await readError(response))
      }

      setDocuments((previous) =>
        previous.filter((item) => item.id !== doc.id)
      )

      // Clear active messages if their document was deleted.
      if (selectedDocumentId === doc.id) {
        setSelectedDocumentId(null)
        setMessages([])
        setQuestion('')
      }

      try {
        const updated = await fetchDocuments()
        setDocuments(updated)

        if (
          selectedDocumentId !== null &&
          !updated.some(
            (item) => item.id === selectedDocumentId
          )
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

  async function askQuestion(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault()

    const text = question.trim()

    if (!text || documents.length === 0 || busy) return

    // Send only the current conversation's previous messages.
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
          history,
        }),
      })

      if (!response.ok) {
        throw new Error(await readError(response))
      }

      const data: AnswerResponse =
        await response.json()

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
            <div className="brand-name">
              Enterprise AI
            </div>

            <div className="brand-subtitle">
              Knowledge Workspace
            </div>
          </div>
        </div>

        <button
          className="new-chat-button"
          disabled={busy}
          onClick={() => createChat()}
        >
          ＋ New chat
        </button>

        {/* MULTIPLE SAVED CONVERSATIONS */}
        <div className="sidebar-section">
          <div className="section-heading">
            RECENT CHATS
          </div>

          <div
            style={{
              maxHeight: 220,
              overflowY: 'auto',
            }}
          >
            {[...chats]
              .sort(
                (a, b) =>
                  b.updatedAt - a.updatedAt
              )
              .map((chat) => (
                <div
                  key={chat.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    borderRadius: 8,
                    background:
                      chat.id === activeChatId
                        ? 'rgba(128,128,128,0.18)'
                        : 'transparent',
                  }}
                >
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => openChat(chat)}
                    title={chat.title}
                    style={{
                      flex: 1,
                      minWidth: 0,
                      textAlign: 'left',
                      padding: '9px 8px',
                      background: 'transparent',
                      border: 0,
                      color: 'inherit',
                      cursor: 'pointer',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {chat.title}
                  </button>

                  <button
                    type="button"
                    disabled={busy}
                    title="Rename chat"
                    aria-label={`Rename ${chat.title}`}
                    onClick={() => renameChat(chat)}
                    style={{
                      border: 0,
                      background: 'transparent',
                      color: 'inherit',
                      cursor: 'pointer',
                      padding: 5,
                    }}
                  >
                    ✎
                  </button>

                  <button
                    type="button"
                    disabled={busy}
                    title="Delete chat"
                    aria-label={`Delete ${chat.title}`}
                    onClick={() => removeChat(chat)}
                    style={{
                      border: 0,
                      background: 'transparent',
                      color: 'inherit',
                      cursor: 'pointer',
                      padding: 5,
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
          </div>
        </div>

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
              selectedDocumentId === null
                ? 'selected'
                : ''
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
                    onClick={() =>
                      selectDocument(doc.id)
                    }
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
                    onClick={() =>
                      void deleteDocument(doc)
                    }
                  >
                    {deletingId === doc.id
                      ? '…'
                      : '×'}
                  </button>
                </div>
              ))}
            </div>
          )}

          <button
            className="upload-secondary"
            disabled={busy}
            onClick={() =>
              fileInputRef.current?.click()
            }
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
              <div className="welcome-icon">
                ✦
              </div>

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
                  onClick={() =>
                    fileInputRef.current?.click()
                  }
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
                  <div className="feature-icon">
                    ⌕
                  </div>

                  <strong>
                    Semantic search
                  </strong>

                  <span>
                    Find relevant information
                    across documents.
                  </span>
                </div>

                <div className="feature-card">
                  <div className="feature-icon">
                    ✧
                  </div>

                  <strong>
                    AI-powered answers
                  </strong>

                  <span>
                    Get responses using retrieved
                    context.
                  </span>
                </div>

                <div className="feature-card">
                  <div className="feature-icon">
                    ▤
                  </div>

                  <strong>
                    Source references
                  </strong>

                  <span>
                    See document names and
                    page numbers.
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
          const file =
            event.target.files?.[0]

          if (file) {
            void uploadDocument(file)
          }
        }}
      />
    </div>
  )
}

export default App
