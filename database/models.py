"""SQLAlchemy 2.0 ORM models."""
from __future__ import annotations

import enum
import re
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, sessionmaker

from config import settings


class Base(DeclarativeBase):
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()


# ─── Enums ───────────────────────────────────────────────────────────
class TradeStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TradeSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeMode(str, enum.Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class OptimizationMethod(str, enum.Enum):
    MANUAL = "MANUAL"
    ATTRIBUTION = "ATTRIBUTION"
    OPTUNA = "OPTUNA"


class EventType(str, enum.Enum):
    BOT_START = "BOT_START"
    BOT_STOP = "BOT_STOP"
    MODE_CHANGE = "MODE_CHANGE"
    TRADE_OPEN = "TRADE_OPEN"
    TRADE_CLOSE = "TRADE_CLOSE"
    ERROR = "ERROR"
    WEIGHTS_UPDATE = "WEIGHTS_UPDATE"
    SETTINGS_CHANGE = "SETTINGS_CHANGE"
    DECISION = "DECISION"
    ANOMALY = "ANOMALY"


class EventSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ─── Tables ──────────────────────────────────────────────────────────
class Trade(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide))
    mode: Mapped[TradeMode] = mapped_column(Enum(TradeMode), default=TradeMode.PAPER)

    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float] = mapped_column(Float)
    leverage: Mapped[float] = mapped_column(Float, default=1.0)

    pnl_usdt: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    fees_usdt: Mapped[float] = mapped_column(Float, default=0.0)

    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, server_default=func.now())
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    signal_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    market_regime: Mapped[str | None] = mapped_column(String(30), nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(10), nullable=True)

    indicators_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_r: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")  # trailing peak (R), persists across restarts
    sl_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    tp_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_close: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[TradeStatus] = mapped_column(Enum(TradeStatus), default=TradeStatus.OPEN, index=True)
    binance_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_trade_symbol_time", "symbol", "entry_time"),)


class Signal(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, server_default=func.now())
    timeframe: Mapped[str] = mapped_column(String(10))

    final_score: Mapped[int] = mapped_column(Integer)
    signal: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[int] = mapped_column(Integer)
    regime: Mapped[str] = mapped_column(String(30))

    trend_score: Mapped[int] = mapped_column(Integer, default=0)
    momentum_score: Mapped[int] = mapped_column(Integer, default=0)
    volatility_score: Mapped[int] = mapped_column(Integer, default=0)
    volume_score: Mapped[int] = mapped_column(Integer, default=0)
    pattern_score: Mapped[int] = mapped_column(Integer, default=0)
    sentiment_score: Mapped[int] = mapped_column(Integer, default=0)

    indicators_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    traded: Mapped[bool] = mapped_column(Boolean, default=False)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trade.id"), nullable=True)

    __table_args__ = (Index("ix_signal_symbol_tf_time", "symbol", "timeframe", "timestamp"),)


class IndicatorWeights(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    regime: Mapped[str] = mapped_column(String(30), index=True)

    trend_w: Mapped[float] = mapped_column(Float)
    momentum_w: Mapped[float] = mapped_column(Float)
    volatility_w: Mapped[float] = mapped_column(Float)
    volume_w: Mapped[float] = mapped_column(Float)
    pattern_w: Mapped[float] = mapped_column(Float)
    sentiment_w: Mapped[float] = mapped_column(Float)

    performance_score: Mapped[float] = mapped_column(Float, default=0.0)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    optimization_method: Mapped[OptimizationMethod] = mapped_column(Enum(OptimizationMethod), default=OptimizationMethod.MANUAL)


class BotSettings(Base):
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped["object"] = mapped_column(JSON)  # any JSON-serializable
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(50), nullable=True)


class SentimentCache(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    fear_greed_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    twitter_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reddit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    funding_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    google_trends_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class BotEvent(Base):
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    event_type: Mapped[EventType] = mapped_column(Enum(EventType))
    severity: Mapped[EventSeverity] = mapped_column(Enum(EventSeverity), default=EventSeverity.INFO)
    message: Mapped[str] = mapped_column(Text)
    event_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# ─── Engine / Session ────────────────────────────────────────────────
engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create all tables. Idempotent."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yields a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
