from sqlalchemy import BigInteger, String, Boolean, DateTime, Integer, Text, Date, ForeignKey, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from typing import List, Optional

Base = declarative_base()


class User(Base):
    """用户模型"""
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language_code: Mapped[str] = mapped_column(String(10), default="en")
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    invited_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=True)

    # 关系
    invitations: Mapped[List["Invitation"]] = relationship("Invitation", back_populates="user")
    challenges: Mapped[List["Challenge"]] = relationship("Challenge", back_populates="user")
    statistics: Mapped[List["Statistic"]] = relationship("Statistic", back_populates="user")
    invited_by: Mapped[Optional["User"]] = relationship("User", remote_side=[user_id], back_populates="invited_users")
    invited_users: Mapped[List["User"]] = relationship("User", back_populates="invited_by")
    invitation_members: Mapped[List["InvitationMember"]] = relationship("InvitationMember", back_populates="invited_user")

    def __repr__(self):
        return f"<User(user_id={self.user_id}, username={self.username})>"


class Invitation(Base):
    """邀请链接模型"""
    __tablename__ = "invitations"

    invite_code: Mapped[str] = mapped_column(String(50), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    invite_link: Mapped[str] = mapped_column(String(500))
    total_invited: Mapped[int] = mapped_column(Integer, default=0)
    total_left: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="invitations")
    members: Mapped[List["InvitationMember"]] = relationship("InvitationMember", back_populates="invitation")

    def __repr__(self):
        return f"<Invitation(invite_code={self.invite_code}, user_id={self.user_id})>"


class InvitationMember(Base):
    """邀请成员模型"""
    __tablename__ = "invitation_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invite_code: Mapped[str] = mapped_column(String(50), ForeignKey("invitations.invite_code"))
    invited_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    has_left: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 关系
    invitation: Mapped["Invitation"] = relationship("Invitation", back_populates="members")
    invited_user: Mapped["User"] = relationship("User", back_populates="invitation_members")

    def __repr__(self):
        return f"<InvitationMember(id={self.id}, invite_code={self.invite_code}, user_id={self.invited_user_id})>"


class Challenge(Base):
    """数学验证挑战模型"""
    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    question: Mapped[str] = mapped_column(Text)
    correct_answer: Mapped[str] = mapped_column(String(50))
    image_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)  # 存储验证码图片
    options: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string of options (保留兼容性)
    user_answer: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_solved: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    solved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="challenges")

    def __repr__(self):
        return f"<Challenge(id={self.id}, user_id={self.user_id}, is_solved={self.is_solved})>"


class Language(Base):
    """语言模型"""
    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    translations: Mapped[dict] = mapped_column(Text)  # Store JSON as text for SQLite compatibility
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self):
        return f"<Language(code={self.code}, name={self.name})>"


class Statistic(Base):
    """统计数据模型"""
    __tablename__ = "statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    metric_type: Mapped[str] = mapped_column(String(50))  # invited_total, kicked_total, etc.
    value: Mapped[int] = mapped_column(Integer)
    date: Mapped[datetime] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="statistics")

    def __repr__(self):
        return f"<Statistic(id={self.id}, user_id={self.user_id}, metric_type={self.metric_type})>"