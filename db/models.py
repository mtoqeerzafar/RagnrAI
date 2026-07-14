import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from db.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    threads = relationship("ChatThread", back_populates="user", cascade="all, delete-orphan")
    documents = relationship("UploadedDocument", back_populates="user", cascade="all, delete-orphan")

class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    s3_key = Column(String, nullable=False, unique=True)
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="documents")

class ChatThread(Base):
    __tablename__ = "chat_threads"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, default="New Chat")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="threads")
    messages = relationship("ChatMessage", back_populates="thread", cascade="all, delete-orphan", order_by="ChatMessage.created_at")

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id = Column(String, ForeignKey("chat_threads.id"), nullable=False, index=True)
    role = Column(String, nullable=False) # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True) # To store verification report, sources, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    
    thread = relationship("ChatThread", back_populates="messages")

class DocumentJob(Base):
    __tablename__ = "document_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, index=True, nullable=False, default="default_tenant")
    thread_id = Column(String, index=True, nullable=True)
    s3_key = Column(String, nullable=False)
    status = Column(String, default="PENDING") # PENDING, PROCESSING, COMPLETED, FAILED
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "thread_id": self.thread_id,
            "s3_key": self.s3_key,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }
