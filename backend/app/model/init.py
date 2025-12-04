from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Float, JSON, ForeignKey, Numeric, Enum as SQLEnum, ARRAY, Interval
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
from enum import Enum
import uuid
from datetime import datetime

Base = declarative_base()

# Import all models
from .user import User, Company, CompanyUser, UserSession, UserPreference
from .transaction import Transaction, TransactionTag, TransactionAttachment, TransactionComment
from .document import Document, BankAccount, BankTransaction, BankConnection
from .report import Report, ReportSchedule, ReportTemplate
from .tax import TaxRecord, TaxCategory, TaxDeduction, TaxForm
from .analytics import Dashboard, Widget, UserActivity, SystemMetric
from .ai import AIModel, AITrainingData, AIResult
from .workflow import Workflow, WorkflowStep, WorkflowExecution
from .notification import Notification, NotificationTemplate, UserNotification
from .integration import Integration, IntegrationLog, Webhook

__all__ = [
    "Base",
    "User", "Company", "CompanyUser", "UserSession", "UserPreference",
    "Transaction", "TransactionTag", "TransactionAttachment", "TransactionComment",
    "Document", "BankAccount", "BankTransaction", "BankConnection",
    "Report", "ReportSchedule", "ReportTemplate",
    "TaxRecord", "TaxCategory", "TaxDeduction", "TaxForm",
    "Dashboard", "Widget", "UserActivity", "SystemMetric",
    "AIModel", "AITrainingData", "AIResult",
    "Workflow", "WorkflowStep", "WorkflowExecution",
    "Notification", "NotificationTemplate", "UserNotification",
    "Integration", "IntegrationLog", "Webhook",
]
