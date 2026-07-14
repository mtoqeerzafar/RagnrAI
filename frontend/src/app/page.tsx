"use client";

import React, { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MessageSquare, Plus, Send, Menu, Bot, User as UserIcon, Loader2, FileText, X, Paperclip } from "lucide-react";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: {id: string, name: string}[];
};

type Thread = {
  thread_id: string;
  title: string;
};

// Use dynamic hostname to support network access
const API_BASE = typeof window !== 'undefined' 
  ? `http://${window.location.hostname}:8000/api` 
  : "http://localhost:8000/api";
  
const TENANT_ID = "default_tenant"; 

export default function ChatApp() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState<{id: string, name: string, status: 'uploading' | 'done' | 'error'}[]>([]);
  
  // Sidebar state
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch threads on mount
  useEffect(() => {
    fetchThreads();
  }, []);

  // Fetch messages when active thread changes
  useEffect(() => {
    if (activeThreadId) {
      fetchMessages(activeThreadId);
    } else {
      setMessages([]);
    }
  }, [activeThreadId]);

  // Smart Auto-scroll: Only scroll to bottom if user is near the bottom
  useEffect(() => {
    if (chatContainerRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = chatContainerRef.current;
      // If within 150px of bottom, auto-scroll (user is reading the latest)
      if (scrollHeight - scrollTop - clientHeight < 150) {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
      }
    } else {
      // If chatContainerRef isn't mounted, fallback to scrolling EndRef
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const fetchThreads = async () => {
    try {
      const res = await fetch(`${API_BASE}/threads`, {
        headers: { "x-tenant-id": TENANT_ID }
      });
      if (res.ok) {
        const data = await res.json();
        setThreads(data);
        if (data.length > 0 && !activeThreadId) {
          setActiveThreadId(data[0].thread_id);
        }
      }
    } catch (e) {
      console.error("Failed to fetch threads", e);
    }
  };

  const fetchMessages = async (threadId: string) => {
    try {
      const res = await fetch(`${API_BASE}/threads/${threadId}/messages`, {
        headers: { "x-tenant-id": TENANT_ID }
      });
      if (res.ok) {
        const data = await res.json();
        setMessages(data);
      }
    } catch (e) {
      console.error("Failed to fetch messages", e);
    }
  };

  const handleNewChat = () => {
    setActiveThreadId(null);
    setMessages([]);
    setUploadedFiles([]);
    setInputValue("");
    // We intentionally don't POST to /threads here. We wait for the first message!
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    let currentThreadId = activeThreadId;
    if (!currentThreadId) {
      try {
        const res = await fetch(`${API_BASE}/threads`, {
          method: "POST",
          headers: { 
            "Content-Type": "application/json",
            "x-tenant-id": TENANT_ID
          },
          body: JSON.stringify({ title: `Document: ${file.name}` })
        });
        if (res.ok) {
          const data = await res.json();
          setThreads(prev => {
            if (prev.some(t => t.thread_id === data.thread_id)) return prev;
            return [data, ...prev];
          });
          setActiveThreadId(data.thread_id);
          currentThreadId = data.thread_id;
        } else {
          throw new Error("Failed to create thread implicitly");
        }
      } catch (err) {
        console.error(err);
        return;
      }
    }

    const fileId = Date.now().toString();
    setUploadedFiles(prev => [...prev, { id: fileId, name: file.name, status: 'uploading' }]);
    
    try {
      const urlRes = await fetch(`${API_BASE}/upload-url?filename=${encodeURIComponent(file.name)}`);
      if (!urlRes.ok) throw new Error("Failed to get upload URL");
      const { upload_url, s3_key } = await urlRes.json();

      const s3Res = await fetch(upload_url, {
        method: "PUT",
        body: file,
      });
      if (!s3Res.ok) throw new Error("Failed to upload to storage");

      const processRes = await fetch(`${API_BASE}/process?s3_key=${encodeURIComponent(s3_key)}&thread_id=${currentThreadId}`, {
        method: "POST",
        headers: { "x-tenant-id": TENANT_ID }
      });
      if (!processRes.ok) throw new Error("Failed to start processing");
      const { job_id } = await processRes.json();

      setUploadedFiles(prev => prev.map(f => f.id === fileId ? { ...f, id: job_id, status: 'done' } : f));
    } catch (err: any) {
      console.error(err);
      setUploadedFiles(prev => prev.map(f => f.id === fileId ? { ...f, status: 'error' } : f));
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const sendMessage = async () => {
    if (!inputValue.trim() || isGenerating) return;

    let currentThreadId = activeThreadId;
    if (!currentThreadId) {
      try {
        const title = inputValue.substring(0, 30) || "New Conversation";
        const res = await fetch(`${API_BASE}/threads`, {
          method: "POST",
          headers: { 
            "Content-Type": "application/json",
            "x-tenant-id": TENANT_ID
          },
          body: JSON.stringify({ title: title })
        });
        if (res.ok) {
          const data = await res.json();
          setThreads(prev => {
            if (prev.some(t => t.thread_id === data.thread_id)) return prev;
            return [data, ...prev];
          });
          setActiveThreadId(data.thread_id);
          currentThreadId = data.thread_id;
        } else {
          throw new Error("Failed to create thread implicitly");
        }
      } catch (err) {
        console.error(err);
        return;
      }
    }

    const attachmentsToSend = uploadedFiles.filter(f => f.status === 'done').map(f => ({id: f.id, name: f.name}));

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: inputValue,
      attachments: attachmentsToSend
    };
    
    setMessages(prev => [...prev, userMessage]);
    setInputValue("");
    setUploadedFiles([]);
    setIsGenerating(true);

    const tempAiMessageId = "temp-" + Date.now();
    setMessages(prev => [...prev, { id: tempAiMessageId, role: "assistant", content: "" }]);

    // Force scroll to bottom immediately upon sending a message
    setTimeout(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 100);

    try {
      const res = await fetch(`${API_BASE}/query/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-tenant-id": TENANT_ID
        },
        body: JSON.stringify({
          question: userMessage.content,
          thread_id: currentThreadId,
          attachments: attachmentsToSend
        })
      });

      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");

      let currentAssistantMessage = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n\n");
        
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const dataStr = line.replace("data: ", "");
            try {
              const data = JSON.parse(dataStr);
              const eventType = data.type || data.node;
              
              if (eventType === "final" || eventType === "answer_end") {
                if (data.answer) {
                  currentAssistantMessage = data.answer;
                }
                setMessages(prev => prev.map(msg => 
                  msg.id === tempAiMessageId ? { ...msg, content: currentAssistantMessage } : msg
                ));
              } else if (eventType === "token") {
                currentAssistantMessage += data.content;
                setMessages(prev => prev.map(msg => 
                  msg.id === tempAiMessageId ? { ...msg, content: currentAssistantMessage } : msg
                ));
              } else if (eventType === "answer_start") {
                currentAssistantMessage = "";
                setMessages(prev => prev.map(msg => 
                  msg.id === tempAiMessageId ? { ...msg, content: "" } : msg
                ));
              } else if (eventType === "status") {
                if (!currentAssistantMessage) {
                  setMessages(prev => prev.map(msg => 
                    msg.id === tempAiMessageId ? { ...msg, content: `*${data.message}*` } : msg
                  ));
                }
              } else if (eventType === "metric") {
                console.log("Metric received:", data);
              } else {
                // Fallback for old schema
                if (!currentAssistantMessage && data.node) {
                  setMessages(prev => prev.map(msg => 
                    msg.id === tempAiMessageId ? { ...msg, content: `*Processing step: ${data.node}...*` } : msg
                  ));
                }
              }
            } catch (err) {
              console.error("Failed to parse SSE", err);
            }
          }
        }
      }
    } catch (e) {
      console.error("Streaming error", e);
      setMessages(prev => prev.map(msg => 
        msg.id === tempAiMessageId ? { ...msg, content: "Sorry, an error occurred while generating the response." } : msg
      ));
    } finally {
      setIsGenerating(false);
      fetchMessages(currentThreadId);
      fetchThreads(); // Refresh thread list in case title was updated
    }
  };

  const InputArea = ({ isCentered }: { isCentered: boolean }) => (
    <div className={`input-container ${isCentered ? "centered" : ""}`}>
      {/* Attachments Area */}
      {uploadedFiles.length > 0 && (
        <div style={{ display: "flex", gap: "10px", marginBottom: "12px", flexWrap: "wrap" }}>
          {uploadedFiles.map(file => (
            <div key={file.id} className="file-chip">
              {file.status === 'uploading' ? (
                <Loader2 size={16} className="spin" color="var(--accent-color)" />
              ) : file.status === 'error' ? (
                <FileText size={16} color="var(--danger-color)" />
              ) : (
                <FileText size={16} color="var(--success-color)" />
              )}
              <span style={{ fontSize: "0.85rem", maxWidth: "200px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {file.name}
              </span>
              <X 
                size={14} 
                style={{ cursor: "pointer", opacity: 0.7 }} 
                onClick={() => setUploadedFiles(prev => prev.filter(f => f.id !== file.id))}
              />
            </div>
          ))}
        </div>
      )}

      <div className="input-box">
        <input 
          type="file" 
          ref={fileInputRef} 
          style={{ display: "none" }} 
          onChange={handleFileUpload}
          accept=".pdf,.txt,.md,.csv,.json"
        />
        
        {/* Top: Text Input */}
        <input 
          type="text" 
          className="text-input"
          placeholder="How can I help you today?" 
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              sendMessage();
            }
          }}
          disabled={isGenerating}
        />
        
        {/* Bottom: Toolbar */}
        <div className="input-toolbar">
          <button 
            className="attach-btn"
            onClick={() => fileInputRef.current?.click()}
            title="Upload Document"
          >
            <Plus size={20} />
          </button>
          
          <button 
            className="send-btn" 
            onClick={sendMessage}
            disabled={!inputValue.trim() || isGenerating}
          >
            <Send size={16} />
          </button>
        </div>
      </div>
      <div style={{ textAlign: "center", fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "12px" }}>
        AI can make mistakes. Please verify critical information.
      </div>
    </div>
  );

  return (
    <div className="app-container">
      {/* Sidebar */}
      <div className={`sidebar ${!isSidebarOpen ? "closed" : ""}`}>
        <div style={{ padding: "16px", display: "flex", alignItems: "center", gap: "12px" }}>
          <Menu 
            size={24} 
            color="var(--text-secondary)" 
            style={{ cursor: "pointer", marginRight: "4px", flexShrink: 0 }} 
            onClick={() => setIsSidebarOpen(false)}
          />
        </div>
        
        <button className="new-chat-btn" onClick={handleNewChat}>
          <Plus size={18} /> New Chat
        </button>
        
        <div style={{ flex: 1, overflowY: "auto", padding: "10px 0" }}>
          <div style={{ padding: "0 16px 8px 16px", fontSize: "0.8rem", color: "var(--text-secondary)", fontWeight: 500 }}>
            Recent
          </div>
          {threads.map(t => (
            <div 
              key={t.thread_id} 
              className={`thread-item ${activeThreadId === t.thread_id ? "active" : ""}`}
              onClick={() => {
                setActiveThreadId(t.thread_id);
                setUploadedFiles([]);
                if (window.innerWidth < 768) setIsSidebarOpen(false); // Auto-close on mobile
              }}
            >
              <MessageSquare size={14} style={{ opacity: 0.7 }} />
              <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {t.title}
              </span>
            </div>
          ))}
        </div>
        
        {/* Profile / Bottom Section */}
        <div style={{ padding: "16px", borderTop: "1px solid var(--border-color)", display: "flex", alignItems: "center", gap: "12px" }}>
           <div style={{ width: "32px", height: "32px", borderRadius: "50%", background: "#444", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.9rem", fontWeight: "bold" }}>
             MT
           </div>
           <div style={{ display: "flex", flexDirection: "column" }}>
             <span style={{ fontSize: "0.9rem" }}>Muhammad Toqeer</span>
             <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>Free plan</span>
           </div>
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="main-chat">
        <div className="chat-header">
          {!isSidebarOpen && (
             <Menu 
               size={24} 
               color="var(--text-secondary)" 
               style={{ cursor: "pointer", marginRight: "16px" }} 
               onClick={() => setIsSidebarOpen(true)}
             />
          )}
          <h3 className="header-title">
            {activeThreadId ? threads.find(t => t.thread_id === activeThreadId)?.title || "" : ""}
          </h3>
        </div>

        {messages.length === 0 ? (
          <div className="empty-state-container">
             <h1 className="serif-heading" style={{ fontSize: "2.2rem", marginBottom: "32px", color: "var(--text-primary)" }}>
                What’s on your mind today?
             </h1>
             <InputArea isCentered={true} />
          </div>
        ) : (
          <>
            <div className="messages-container" ref={chatContainerRef}>
              {messages.map((msg) => (
                <div key={msg.id} className={`message-wrapper ${msg.role}`}>
                  <div style={{ display: "flex", flexDirection: "row", gap: "16px", maxWidth: "100%", width: "100%" }}>
                    
                    {/* Avatar */}
                    {msg.role === "assistant" && (
                      <div style={{ 
                        width: "32px", height: "32px", borderRadius: "6px", display: "flex", alignItems: "center", justifyContent: "center",
                        background: "var(--accent-color)", flexShrink: 0, marginTop: "4px"
                      }}>
                        <Bot size={20} color="white" />
                      </div>
                    )}
                    
                    <div className="message-bubble" style={{ flex: 1, padding: msg.role === "assistant" ? "0 12px" : "12px 16px" }}>
                      
                      {/* Name Header */}
                      <div style={{ fontWeight: 600, fontSize: "0.9rem", marginBottom: "8px", color: msg.role === "user" ? "var(--text-secondary)" : "var(--accent-color)" }}>
                         {msg.role === "user" ? "You" : "RagnrAI"}
                      </div>
                      
                      {msg.attachments && msg.attachments.length > 0 && (
                        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "12px" }}>
                          {msg.attachments.map(att => (
                            <div key={att.id} style={{ 
                              background: "var(--bg-secondary)", padding: "6px 12px", borderRadius: "6px", 
                              fontSize: "0.85rem", display: "flex", alignItems: "center", gap: "6px",
                              border: "1px solid var(--border-color)"
                            }}>
                              <FileText size={14} /> {att.name}
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {msg.role === "assistant" ? (
                        <div className="markdown">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                      ) : (
                        <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{msg.content}</div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} style={{ height: "40px" }} />
            </div>
            
            <InputArea isCentered={false} />
          </>
        )}
      </div>
    </div>
  );
}
