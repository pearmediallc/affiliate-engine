'use client';

import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { API_BASE_URL, API_HOST } from '@/lib/api';

function getImageSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith('/api/')) return `${API_HOST}${url}`;
  return url;
}

type SubTab = 'overview' | 'users' | 'feedback' | 'suggestions' | 'learning' | 'models' | 'generations' | 'audit';

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------

const styles = {
  page: {
    minHeight: '100vh',
    padding: '32px 24px',
  } as React.CSSProperties,
  card: {
    background: 'rgba(20, 20, 22, 0.65)',
    backdropFilter: 'blur(20px)',
    borderRadius: '10px',
    border: '1px solid rgba(255,255,255,0.08)',
    boxShadow: '0 4px 24px rgba(0,0,0,0.3)',
    padding: '24px',
    color: '#e8e8ed',
  } as React.CSSProperties,
  heading: {
    fontSize: '24px',
    fontWeight: 700,
    color: '#ffffff',
    letterSpacing: '-0.4px',
    margin: 0,
  } as React.CSSProperties,
  subHeading: {
    fontSize: '17px',
    fontWeight: 600,
    color: '#f0f0f5',
    margin: '0 0 16px',
  } as React.CSSProperties,
  tabBar: {
    display: 'flex',
    gap: '4px',
    marginBottom: '24px',
    borderBottom: '1px solid rgba(255,255,255,0.08)',
    paddingBottom: '0',
  } as React.CSSProperties,
  tab: (active: boolean): React.CSSProperties => ({
    padding: '10px 18px',
    fontSize: '13px',
    fontWeight: 500,
    color: active ? '#2997ff' : 'rgba(255,255,255,0.5)',
    background: 'transparent',
    border: 'none',
    borderBottom: active ? '2px solid #0071e3' : '2px solid transparent',
    cursor: 'pointer',
    letterSpacing: '-0.08px',
    transition: 'color 0.15s, border-color 0.15s',
  }),
  btnPrimary: {
    background: '#0071e3',
    color: '#fff',
    border: 'none',
    borderRadius: '6px',
    padding: '7px 16px',
    fontSize: '13px',
    fontWeight: 500,
    cursor: 'pointer',
    letterSpacing: '-0.08px',
  } as React.CSSProperties,
  btnSecondary: {
    background: 'rgba(255,255,255,0.08)',
    color: '#e8e8ed',
    border: '1px solid rgba(255,255,255,0.15)',
    borderRadius: '6px',
    padding: '7px 16px',
    fontSize: '13px',
    fontWeight: 500,
    cursor: 'pointer',
    letterSpacing: '-0.08px',
  } as React.CSSProperties,
  btnDanger: {
    background: 'rgba(255,59,48,0.1)',
    color: '#ff6b6b',
    border: '1px solid rgba(255,59,48,0.24)',
    borderRadius: '6px',
    padding: '7px 16px',
    fontSize: '13px',
    fontWeight: 500,
    cursor: 'pointer',
  } as React.CSSProperties,
  select: {
    appearance: 'none' as const,
    background: 'rgba(255,255,255,0.08)',
    border: '1px solid rgba(255,255,255,0.12)',
    borderRadius: '6px',
    padding: '6px 28px 6px 10px',
    fontSize: '13px',
    color: '#e8e8ed',
    cursor: 'pointer',
    backgroundImage: `url("data:image/svg+xml,%3Csvg width='10' height='6' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23999'/%3E%3C/svg%3E")`,
    backgroundRepeat: 'no-repeat',
    backgroundPosition: 'right 10px center',
  } as React.CSSProperties,
  th: {
    textAlign: 'left' as const,
    padding: '12px 16px',
    fontSize: '12px',
    fontWeight: 600,
    color: 'rgba(255,255,255,0.4)',
    letterSpacing: '-0.12px',
    textTransform: 'uppercase' as const,
  } as React.CSSProperties,
  td: {
    padding: '12px 16px',
    fontSize: '14px',
    color: '#e8e8ed',
  } as React.CSSProperties,
  statValue: {
    fontSize: '32px',
    fontWeight: 700,
    color: '#ffffff',
    letterSpacing: '-0.6px',
    margin: '8px 0 0',
  } as React.CSSProperties,
  statLabel: {
    fontSize: '13px',
    color: 'rgba(255,255,255,0.45)',
    fontWeight: 500,
    margin: 0,
  } as React.CSSProperties,
  spinner: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    padding: '48px',
    color: 'rgba(255,255,255,0.4)',
    fontSize: '14px',
  } as React.CSSProperties,
  empty: {
    textAlign: 'center' as const,
    padding: '48px',
    color: 'rgba(255,255,255,0.35)',
    fontSize: '14px',
  } as React.CSSProperties,
  thumbnail: {
    width: '48px',
    height: '48px',
    objectFit: 'cover' as const,
    borderRadius: '6px',
    background: 'rgba(255,255,255,0.05)',
  } as React.CSSProperties,
  badge: (color: string): React.CSSProperties => ({
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: '4px',
    fontSize: '12px',
    fontWeight: 500,
    background: color === 'green' ? 'rgba(48,209,88,0.15)' : color === 'red' ? 'rgba(255,69,58,0.15)' : color === 'blue' ? 'rgba(41,151,255,0.15)' : 'rgba(255,255,255,0.08)',
    color: color === 'green' ? '#30d158' : color === 'red' ? '#ff6b6b' : color === 'blue' ? '#2997ff' : '#e8e8ed',
  }),
};

// ---------------------------------------------------------------------------
// Overview Tab
// ---------------------------------------------------------------------------

function OverviewTab() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    axios
      .get(`${API_BASE_URL}/admin/dashboard`)
      .then((r) => setStats(r.data.data ?? r.data))
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div style={styles.spinner}>Loading overview...</div>;
  if (!stats) return <div style={styles.empty}>Failed to load dashboard stats.</div>;

  const cards: { label: string; value: string }[] = [
    { label: 'Total Users', value: String(stats.total_users ?? 0) },
    { label: 'Total Generations', value: String(stats.total_generations ?? 0) },
    { label: 'Total Spend', value: `$${(stats.total_spend ?? 0).toFixed(2)}` },
    { label: 'Avg Satisfaction', value: `${((stats.avg_satisfaction ?? 0) * 100).toFixed(0)}%` },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '16px' }}>
      {cards.map((c) => (
        <div key={c.label} style={styles.card}>
          <p style={styles.statLabel}>{c.label}</p>
          <p style={styles.statValue}>{c.value}</p>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Users Tab
// ---------------------------------------------------------------------------

function UsersTab() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [rejecting, setRejecting] = useState<{ id: string; email: string } | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [actionMsg, setActionMsg] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'approved' | 'rejected'>('all');

  const fetchUsers = useCallback(() => {
    setLoading(true);
    axios
      .get(`${API_BASE_URL}/auth/users`)
      .then((r) => {
        const d = r.data?.data;
        setUsers(Array.isArray(d) ? d : d?.users ?? []);
      })
      .catch(() => setUsers([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const handleRoleChange = async (userId: string, newRole: string) => {
    try {
      await axios.put(`${API_BASE_URL}/auth/users/${userId}/role`, { role: newRole });
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u)));
    } catch {
      // silent
    }
  };

  const handleDeactivate = async (userId: string, currentlyActive: boolean) => {
    try {
      await axios.put(`${API_BASE_URL}/auth/users/${userId}/deactivate`);
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, is_active: !currentlyActive } : u)),
      );
    } catch {
      // silent
    }
  };

  const handleApprove = async (userId: string) => {
    try {
      const r = await axios.post(`${API_BASE_URL}/auth/users/${userId}/approve`);
      const updated = r.data?.data;
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, ...updated } : u)));
      setActionMsg({ text: 'User approved', type: 'success' });
    } catch (e) {
      setActionMsg({ text: 'Approval failed', type: 'error' });
    }
  };

  const handleReject = async () => {
    if (!rejecting) return;
    try {
      const r = await axios.post(`${API_BASE_URL}/auth/users/${rejecting.id}/reject`, {
        reason: rejectReason,
      });
      const updated = r.data?.data;
      setUsers((prev) => prev.map((u) => (u.id === rejecting.id ? { ...u, ...updated } : u)));
      setActionMsg({ text: `Rejected ${rejecting.email}`, type: 'success' });
      setRejecting(null);
      setRejectReason('');
    } catch {
      setActionMsg({ text: 'Rejection failed', type: 'error' });
    }
  };

  const pendingUsers = users.filter((u) => (u.status || 'approved') === 'pending');
  const filteredUsers = statusFilter === 'all'
    ? users
    : users.filter((u) => (u.status || 'approved') === statusFilter);

  const statusBadgeColor = (status: string, isActive: boolean) => {
    if (status === 'pending') return 'blue';
    if (status === 'rejected') return 'red';
    if (!isActive) return 'gray';
    return 'green';
  };
  const statusLabel = (status: string, isActive: boolean) => {
    if (status === 'pending') return 'Pending';
    if (status === 'rejected') return 'Rejected';
    if (!isActive) return 'Inactive';
    return 'Active';
  };

  if (loading) return <div style={styles.spinner}>Loading users...</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Action bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <button style={styles.btnPrimary} onClick={() => setShowCreate(true)}>+ Create User</button>
        <select
          style={styles.select}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as 'all' | 'pending' | 'approved' | 'rejected')}
        >
          <option value="all">All ({users.length})</option>
          <option value="pending">Pending ({pendingUsers.length})</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
        {actionMsg && (
          <span style={{ fontSize: '13px', color: actionMsg.type === 'success' ? '#30d158' : '#ff6b6b' }}>
            {actionMsg.text}
          </span>
        )}
      </div>

      {/* Pending highlight banner */}
      {pendingUsers.length > 0 && statusFilter !== 'pending' && (
        <div
          style={{
            padding: '12px 16px',
            background: 'rgba(41,151,255,0.1)',
            border: '1px solid rgba(41,151,255,0.25)',
            borderRadius: '8px',
            cursor: 'pointer',
            fontSize: '13px',
            color: '#2997ff',
          }}
          onClick={() => setStatusFilter('pending')}
        >
          {pendingUsers.length} user{pendingUsers.length === 1 ? '' : 's'} awaiting your approval — click to review →
        </div>
      )}

      {/* Users table */}
      <div style={styles.card}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
              <th style={styles.th}>Email</th>
              <th style={styles.th}>Name</th>
              <th style={styles.th}>Role</th>
              <th style={styles.th}>Status</th>
              <th style={styles.th}>Last Login</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredUsers.length === 0 && (
              <tr><td colSpan={6} style={styles.empty}>No users to show.</td></tr>
            )}
            {filteredUsers.map((u, idx) => {
              const status = u.status || 'approved';
              const isPending = status === 'pending';
              const isRejected = status === 'rejected';
              return (
                <tr key={u.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', background: idx % 2 === 1 ? 'rgba(255,255,255,0.03)' : 'transparent' }}>
                  <td style={styles.td}>{u.email}</td>
                  <td style={styles.td}>{u.full_name || '--'}</td>
                  <td style={styles.td}>
                    <select
                      style={styles.select}
                      value={u.role}
                      disabled={isPending || isRejected}
                      onChange={(e) => handleRoleChange(u.id, e.target.value)}
                    >
                      <option value="viewer">viewer</option>
                      <option value="editor">editor</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td style={styles.td}>
                    <span style={styles.badge(statusBadgeColor(status, u.is_active))}>
                      {statusLabel(status, u.is_active)}
                    </span>
                    {isRejected && u.rejection_reason && (
                      <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.45)', margin: '4px 0 0' }}>
                        {u.rejection_reason}
                      </p>
                    )}
                  </td>
                  <td style={styles.td}>
                    {u.last_login ? new Date(u.last_login).toLocaleDateString() : '--'}
                  </td>
                  <td style={styles.td}>
                    {isPending ? (
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button style={styles.btnPrimary} onClick={() => handleApprove(u.id)}>Approve</button>
                        <button style={styles.btnDanger} onClick={() => { setRejecting({ id: u.id, email: u.email }); setRejectReason(''); }}>Reject</button>
                      </div>
                    ) : isRejected ? (
                      <button style={styles.btnPrimary} onClick={() => handleApprove(u.id)}>Approve</button>
                    ) : (
                      <button
                        style={u.is_active ? styles.btnDanger : styles.btnPrimary}
                        onClick={() => handleDeactivate(u.id, u.is_active)}
                      >
                        {u.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showCreate && <CreateUserModal onClose={() => setShowCreate(false)} onCreated={(u) => { setUsers((prev) => [u, ...prev]); setShowCreate(false); setActionMsg({ text: `Created ${u.email}`, type: 'success' }); }} />}
      {rejecting && (
        <RejectModal
          email={rejecting.email}
          reason={rejectReason}
          setReason={setRejectReason}
          onCancel={() => { setRejecting(null); setRejectReason(''); }}
          onConfirm={handleReject}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create-user modal
// ---------------------------------------------------------------------------

function CreateUserModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onCreated: (user: any) => void;
}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [role, setRole] = useState('viewer');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const r = await axios.post(`${API_BASE_URL}/auth/users`, {
        email, password, full_name: fullName || undefined, role,
      });
      onCreated(r.data?.data);
    } catch (err) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const e = err as any;
      setError(e?.response?.data?.detail || 'Failed to create user');
    } finally {
      setSubmitting(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '10px 14px',
    background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: '8px', color: '#e8e8ed', fontSize: '14px', outline: 'none',
  };
  const labelStyle: React.CSSProperties = {
    display: 'block', fontSize: '12px', fontWeight: 600,
    color: 'rgba(255,255,255,0.6)', marginBottom: '6px',
    textTransform: 'uppercase', letterSpacing: '0.4px',
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000, padding: '24px',
    }}
      onClick={onClose}
    >
      <div
        style={{
          background: 'rgba(25, 25, 28, 0.98)', backdropFilter: 'blur(24px)',
          borderRadius: '14px', border: '1px solid rgba(255,255,255,0.1)',
          padding: '28px', maxWidth: '420px', width: '100%',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ fontSize: '20px', fontWeight: 600, color: '#fff', margin: '0 0 6px' }}>Create User</h3>
        <p style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)', margin: '0 0 20px' }}>
          Admin-created users are auto-approved and can sign in immediately.
        </p>

        {error && (
          <div style={{ padding: '10px 14px', marginBottom: '16px', background: 'rgba(255,59,48,0.12)', borderLeft: '3px solid #ff3b30', borderRadius: '6px' }}>
            <p style={{ fontSize: '13px', color: '#ff6b6b', margin: 0 }}>{error}</p>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '14px' }}>
            <label style={labelStyle}>Email</label>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} style={inputStyle} placeholder="user@example.com" />
          </div>
          <div style={{ marginBottom: '14px' }}>
            <label style={labelStyle}>Password</label>
            <input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} style={inputStyle} placeholder="At least 8 characters" />
          </div>
          <div style={{ marginBottom: '14px' }}>
            <label style={labelStyle}>Full Name (optional)</label>
            <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} style={inputStyle} />
          </div>
          <div style={{ marginBottom: '20px' }}>
            <label style={labelStyle}>Role</label>
            <select value={role} onChange={(e) => setRole(e.target.value)} style={{ ...inputStyle, cursor: 'pointer' }}>
              <option value="viewer">viewer</option>
              <option value="editor">editor</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
            <button type="button" onClick={onClose} style={styles.btnSecondary}>Cancel</button>
            <button type="submit" disabled={submitting || !email || !password} style={{ ...styles.btnPrimary, opacity: submitting || !email || !password ? 0.6 : 1 }}>
              {submitting ? 'Creating...' : 'Create User'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Reject-user modal
// ---------------------------------------------------------------------------

function RejectModal({
  email, reason, setReason, onCancel, onConfirm,
}: {
  email: string;
  reason: string;
  setReason: (v: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000, padding: '24px',
      }}
      onClick={onCancel}
    >
      <div
        style={{
          background: 'rgba(25,25,28,0.98)', backdropFilter: 'blur(24px)',
          borderRadius: '14px', border: '1px solid rgba(255,255,255,0.1)',
          padding: '28px', maxWidth: '420px', width: '100%',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ fontSize: '20px', fontWeight: 600, color: '#fff', margin: '0 0 6px' }}>Reject Registration</h3>
        <p style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)', margin: '0 0 20px' }}>
          Reason will be shown to <strong style={{ color: '#fff' }}>{email}</strong> on their next login attempt.
        </p>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder="e.g. Email domain not on allowlist; please use your work email."
          style={{
            width: '100%', padding: '10px 14px',
            background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: '8px', color: '#e8e8ed', fontSize: '14px',
            outline: 'none', resize: 'vertical', marginBottom: '16px',
          }}
        />
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={styles.btnSecondary}>Cancel</button>
          <button onClick={onConfirm} style={styles.btnDanger}>Reject User</button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feedback Tab
// ---------------------------------------------------------------------------

function FeedbackTab() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [vertical, setVertical] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  const fetchFeedback = useCallback(() => {
    setLoading(true);
    const params: Record<string, string | number> = { rating: 'negative', page, page_size: 20 };
    if (vertical) params.vertical = vertical;
    axios
      .get(`${API_BASE_URL}/admin/feedback`, { params })
      .then((r) => {
        const d = r.data?.data ?? r.data;
        const feedbackList = Array.isArray(d) ? d : d?.items ?? d?.feedback ?? [];
        setItems(feedbackList);
        setTotalPages(d?.total_pages ?? 1);
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [vertical, page]);

  useEffect(() => { fetchFeedback(); }, [fetchFeedback]);

  const truncate = (s: string | null | undefined, len: number) => {
    if (!s) return '--';
    return s.length > len ? s.slice(0, len) + '...' : s;
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
        <label style={{ fontSize: '13px', color: 'rgba(0,0,0,0.56)' }}>Vertical</label>
        <select style={styles.select} value={vertical} onChange={(e) => { setVertical(e.target.value); setPage(1); }}>
          <option value="">All</option>
          {['supplements', 'skincare', 'fitness', 'tech', 'fashion', 'food', 'home', 'pets'].map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </div>

      <div style={styles.card}>
        {loading ? (
          <div style={styles.spinner}>Loading feedback...</div>
        ) : items.length === 0 ? (
          <div style={styles.empty}>No negative feedback found.</div>
        ) : (
          <>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(0,0,0,0.08)' }}>
                  <th style={styles.th}>Image</th>
                  <th style={styles.th}>Prompt</th>
                  <th style={styles.th}>Provider</th>
                  <th style={styles.th}>Cost</th>
                  <th style={styles.th}>Rating</th>
                  <th style={styles.th}>Issues</th>
                  <th style={styles.th}>Comment</th>
                  <th style={styles.th}>User</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, idx) => {
                  const src = getImageSrc(item.image_url ?? item.thumbnail_url);
                  return (
                    <tr key={item.id ?? idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', background: idx % 2 === 1 ? 'rgba(255,255,255,0.03)' : 'transparent' }}>
                      <td style={styles.td}>
                        {src ? (
                          <img src={src} alt="" style={styles.thumbnail} />
                        ) : (
                          <div style={{ ...styles.thumbnail, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'rgba(0,0,0,0.2)', fontSize: '11px' }}>--</div>
                        )}
                      </td>
                      <td style={{ ...styles.td, maxWidth: '200px' }}>{truncate(item.prompt, 60)}</td>
                      <td style={styles.td}>{item.provider ?? '--'}</td>
                      <td style={styles.td}>{item.cost != null ? `$${Number(item.cost).toFixed(3)}` : '--'}</td>
                      <td style={styles.td}>
                        <span style={styles.badge(item.rating === 'positive' ? 'green' : 'red')}>{item.rating}</span>
                      </td>
                      <td style={{ ...styles.td, maxWidth: '160px' }}>
                        {item.issues && item.issues.length > 0 ? item.issues.join(', ') : '--'}
                      </td>
                      <td style={{ ...styles.td, maxWidth: '160px' }}>{truncate(item.comment, 50)}</td>
                      <td style={styles.td}>{item.user_email ?? '--'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {totalPages > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', gap: '8px', marginTop: '16px' }}>
                <button style={styles.btnSecondary} disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</button>
                <span style={{ fontSize: '13px', color: 'rgba(0,0,0,0.48)', lineHeight: '32px' }}>Page {page} of {totalPages}</span>
                <button style={styles.btnSecondary} disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next</button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AI Suggestions Tab
// ---------------------------------------------------------------------------

function SuggestionsTab() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [vertical, setVertical] = useState('');
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchSuggestions = useCallback(() => {
    setLoading(true);
    const params: Record<string, string> = { status: 'pending' };
    if (vertical) params.vertical = vertical;
    axios
      .get(`${API_BASE_URL}/admin/ai-suggestions`, { params })
      .then((r) => {
        const d = r.data?.data;
        setItems(Array.isArray(d) ? d : d?.suggestions ?? d?.items ?? []);
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [vertical]);

  useEffect(() => { fetchSuggestions(); }, [fetchSuggestions]);

  const handleAction = async (id: string, action: 'approve' | 'reject') => {
    setActionLoading(id);
    try {
      await axios.post(`${API_BASE_URL}/admin/ai-suggestions/${id}/${action}`);
      setItems((prev) => prev.filter((s) => s.id !== id));
    } catch {
      // silent
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
        <label style={{ fontSize: '13px', color: 'rgba(0,0,0,0.56)' }}>Vertical</label>
        <select style={styles.select} value={vertical} onChange={(e) => setVertical(e.target.value)}>
          <option value="">All</option>
          {['supplements', 'skincare', 'fitness', 'tech', 'fashion', 'food', 'home', 'pets'].map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div style={styles.spinner}>Loading suggestions...</div>
      ) : items.length === 0 ? (
        <div style={{ ...styles.card, ...styles.empty }}>No pending suggestions.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {items.map((s) => (
            <div key={s.id} style={styles.card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px' }}>
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: '15px', fontWeight: 500, color: '#f0f0f5', margin: '0 0 6px' }}>{s.suggestion ?? s.text ?? '--'}</p>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '8px' }}>
                    {s.category && <span style={styles.badge('blue')}>{s.category}</span>}
                    {s.vertical && <span style={styles.badge('gray')}>{s.vertical}</span>}
                  </div>
                  {(s.confidence != null || s.evidence_count != null) && (
                    <p style={{ fontSize: '12px', color: 'rgba(0,0,0,0.48)', margin: 0 }}>
                      {s.confidence != null && `Confidence: ${(s.confidence * 100).toFixed(0)}%`}
                      {s.confidence != null && s.evidence_count != null && ' / '}
                      {s.evidence_count != null && `Evidence: ${s.evidence_count} records`}
                    </p>
                  )}
                </div>
                <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
                  <button
                    style={styles.btnPrimary}
                    disabled={actionLoading === s.id}
                    onClick={() => handleAction(s.id, 'approve')}
                  >
                    Approve
                  </button>
                  <button
                    style={styles.btnSecondary}
                    disabled={actionLoading === s.id}
                    onClick={() => handleAction(s.id, 'reject')}
                  >
                    Reject
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Learning Tab
// ---------------------------------------------------------------------------

function LearningTab() {
  const [vertical, setVertical] = useState('supplements');
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);

  const fetchStats = useCallback(() => {
    setLoading(true);
    axios
      .get(`${API_BASE_URL}/admin/learning/${vertical}`)
      .then((r) => setStats(r.data.data ?? r.data))
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, [vertical]);

  useEffect(() => { fetchStats(); }, [fetchStats]);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      await axios.post(`${API_BASE_URL}/admin/ai-suggestions/analyze/${vertical}`);
      fetchStats();
    } catch {
      // silent
    } finally {
      setAnalyzing(false);
    }
  };

  const verticals = ['supplements', 'skincare', 'fitness', 'tech', 'fashion', 'food', 'home', 'pets'];

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
        <label style={{ fontSize: '13px', color: 'rgba(0,0,0,0.56)' }}>Vertical</label>
        <select style={styles.select} value={vertical} onChange={(e) => setVertical(e.target.value)}>
          {verticals.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
        <button style={styles.btnPrimary} onClick={handleAnalyze} disabled={analyzing}>
          {analyzing ? 'Analyzing...' : 'Analyze Now'}
        </button>
      </div>

      {loading ? (
        <div style={styles.spinner}>Loading learning stats...</div>
      ) : !stats ? (
        <div style={{ ...styles.card, ...styles.empty }}>No learning data for this vertical.</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '16px' }}>
          <div style={styles.card}>
            <p style={styles.statLabel}>Total Records</p>
            <p style={styles.statValue}>{stats.total_records ?? 0}</p>
          </div>
          <div style={styles.card}>
            <p style={styles.statLabel}>Satisfaction</p>
            <p style={styles.statValue}>
              {stats.satisfaction_rate != null ? `${(stats.satisfaction_rate * 100).toFixed(0)}%` : '--'}
            </p>
          </div>
          <div style={styles.card}>
            <p style={styles.statLabel}>Learned Rules</p>
            <p style={styles.statValue}>{stats.learned_rules_count ?? stats.rules_count ?? 0}</p>
          </div>
          <div style={styles.card}>
            <p style={styles.statLabel}>Last Analyzed</p>
            <p style={{ ...styles.statValue, fontSize: '18px' }}>
              {stats.last_analyzed ? new Date(stats.last_analyzed).toLocaleString() : 'Never'}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Models Tab
// ---------------------------------------------------------------------------

function ModelsTab() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [config, setConfig] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const [primaryProvider, setPrimaryProvider] = useState('gemini');
  const [geminiImageModel, setGeminiImageModel] = useState('imagen-4.0-generate-001');

  const fetchConfig = useCallback(() => {
    setLoading(true);
    axios
      .get(`${API_BASE_URL}/admin/model-config`)
      .then((r) => {
        const d = r.data?.data ?? r.data;
        setConfig(d);
        setPrimaryProvider(d?.image_generation?.primary ?? 'gemini');
        setGeminiImageModel(d?.image_model ?? 'imagen-4.0-generate-001');
      })
      .catch(() => setConfig(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchConfig(); }, [fetchConfig]);

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await axios.put(`${API_BASE_URL}/admin/model-config`, {
        primary_provider: primaryProvider,
        gemini_image_model: geminiImageModel,
      });
      setMessage({ text: 'Model configuration saved (runtime only, resets on restart)', type: 'success' });
      fetchConfig();
    } catch {
      setMessage({ text: 'Failed to save model configuration', type: 'error' });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div style={styles.spinner}>Loading model config...</div>;
  if (!config) return <div style={styles.empty}>Failed to load model configuration.</div>;

  const providers = ['gemini', 'openai', 'fal'] as const;
  const models = config?.image_generation?.models ?? {};

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Provider Priority */}
      <div style={styles.card}>
        <h3 style={styles.subHeading}>Image Generation Providers</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: '16px' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
              <th style={styles.th}>Provider</th>
              <th style={styles.th}>Model</th>
              <th style={styles.th}>API Key</th>
              <th style={styles.th}>Priority</th>
            </tr>
          </thead>
          <tbody>
            {providers.map((p, idx) => {
              const info = models[p] ?? {};
              const isPrimary = p === primaryProvider;
              return (
                <tr key={p} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', background: idx % 2 === 1 ? 'rgba(255,255,255,0.03)' : 'transparent' }}>
                  <td style={styles.td}>
                    <span style={{ fontWeight: isPrimary ? 600 : 400, color: isPrimary ? '#2997ff' : '#e8e8ed' }}>
                      {p.charAt(0).toUpperCase() + p.slice(1)}
                    </span>
                  </td>
                  <td style={styles.td}>{info.model ?? '--'}</td>
                  <td style={styles.td}>
                    <span style={styles.badge(info.status === 'available' ? 'green' : 'red')}>
                      {info.status === 'available' ? 'Configured' : 'Missing'}
                    </span>
                  </td>
                  <td style={styles.td}>
                    {isPrimary ? (
                      <span style={styles.badge('blue')}>Primary</span>
                    ) : (
                      <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.4)' }}>--</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Configuration Controls */}
      <div style={styles.card}>
        <h3 style={styles.subHeading}>Configuration</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <label style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)', minWidth: '160px' }}>Primary Provider</label>
            <select style={styles.select} value={primaryProvider} onChange={(e) => setPrimaryProvider(e.target.value)}>
              {providers.map((p) => (
                <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
              ))}
            </select>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <label style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)', minWidth: '160px' }}>Gemini Image Model</label>
            <select style={styles.select} value={geminiImageModel} onChange={(e) => setGeminiImageModel(e.target.value)}>
              <option value="imagen-4.0-generate-001">imagen-4.0-generate-001</option>
              <option value="gemini-2.5-flash-image">gemini-2.5-flash-image</option>
            </select>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '20px' }}>
          <button style={styles.btnPrimary} onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save'}
          </button>
          {message && (
            <span style={{ fontSize: '13px', color: message.type === 'success' ? '#30d158' : '#ff6b6b' }}>
              {message.text}
            </span>
          )}
        </div>
      </div>

      {/* Read-only Info */}
      <div style={styles.card}>
        <h3 style={styles.subHeading}>Other AI Models</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', gap: '12px' }}>
            <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)', minWidth: '160px' }}>Text AI Model</span>
            <span style={{ fontSize: '13px', color: '#e8e8ed' }}>{config?.text_ai?.model ?? '--'}</span>
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)', minWidth: '160px' }}>Hook Analyzer</span>
            <span style={{ fontSize: '13px', color: '#e8e8ed' }}>{config?.hook_analyzer ?? '--'}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Generations Tab
// ---------------------------------------------------------------------------

const GEN_JOB_TYPE_LABELS: Record<string, string> = {
  image_generation: 'Image',
  ugc_video: 'UGC Video',
  talking_head: 'Talking Head',
  veo_video: 'Video',
  script_generation: 'Script',
  ad_copy: 'Ad Copy',
  landing_page: 'Landing Page',
  lp_analysis: 'LP Analysis',
  angle_generation: 'Angles',
};

const GEN_STATUS_COLORS: Record<string, string> = {
  processing: 'yellow',
  completed: 'green',
  failed: 'red',
  pending: 'gray',
};

function GenerationsTab() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [jobs, setJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ user_id: '', job_type: '', status: '', vertical: '' });
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [feedbackJobId, setFeedbackJobId] = useState('');
  const [feedbackRating, setFeedbackRating] = useState('');
  const [feedbackComment, setFeedbackComment] = useState('');

  const fetchJobs = useCallback(() => {
    setLoading(true);
    const params: Record<string, string | number> = { page, page_size: 30 };
    if (filters.user_id) params.user_id = filters.user_id;
    if (filters.job_type) params.job_type = filters.job_type;
    if (filters.status) params.status = filters.status;
    if (filters.vertical) params.vertical = filters.vertical;

    axios.get(`${API_BASE_URL}/jobs/admin/all`, { params })
      .then(r => {
        const d = r.data?.data || {};
        setJobs(d.jobs || []);
        setTotalPages(d.total_pages || 1);
      })
      .catch(() => setJobs([]))
      .finally(() => setLoading(false));
  }, [filters, page]);

  useEffect(() => { fetchJobs(); }, [fetchJobs]);

  const submitFeedback = async (jobId: string) => {
    if (!feedbackRating) return;
    try {
      await axios.post(`${API_BASE_URL}/jobs/admin/${jobId}/feedback`, {
        rating: feedbackRating,
        comment: feedbackComment,
      });
      setFeedbackJobId('');
      setFeedbackRating('');
      setFeedbackComment('');
      fetchJobs();
    } catch {
      // silent
    }
  };

  const updateFilter = (key: string, value: string) => {
    setFilters(prev => ({ ...prev, [key]: value }));
    setPage(1);
  };

  const jobTypes = ['image_generation', 'ugc_video', 'talking_head', 'veo_video', 'script_generation', 'ad_copy', 'landing_page', 'lp_analysis', 'angle_generation'];
  const statuses = ['pending', 'processing', 'completed', 'failed'];
  const verticals = ['supplements', 'skincare', 'fitness', 'tech', 'fashion', 'food', 'home', 'pets', 'home_insurance'];

  return (
    <div>
      {/* Filters */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label style={{ fontSize: '12px', color: 'rgba(255,255,255,0.45)' }}>Type</label>
          <select style={styles.select} value={filters.job_type} onChange={e => updateFilter('job_type', e.target.value)}>
            <option value="">All</option>
            {jobTypes.map(t => <option key={t} value={t}>{GEN_JOB_TYPE_LABELS[t] || t}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label style={{ fontSize: '12px', color: 'rgba(255,255,255,0.45)' }}>Status</label>
          <select style={styles.select} value={filters.status} onChange={e => updateFilter('status', e.target.value)}>
            <option value="">All</option>
            {statuses.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label style={{ fontSize: '12px', color: 'rgba(255,255,255,0.45)' }}>Vertical</label>
          <select style={styles.select} value={filters.vertical} onChange={e => updateFilter('vertical', e.target.value)}>
            <option value="">All</option>
            {verticals.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <label style={{ fontSize: '12px', color: 'rgba(255,255,255,0.45)' }}>User ID</label>
          <input
            type="text"
            placeholder="Filter by user ID..."
            value={filters.user_id}
            onChange={e => updateFilter('user_id', e.target.value)}
            style={{
              background: 'rgba(255,255,255,0.08)',
              border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: '6px',
              padding: '6px 10px',
              fontSize: '13px',
              color: '#e8e8ed',
              width: '180px',
            }}
          />
        </div>
      </div>

      {/* Table */}
      <div style={styles.card}>
        {loading ? (
          <div style={styles.spinner}>Loading generations...</div>
        ) : jobs.length === 0 ? (
          <div style={styles.empty}>No jobs found.</div>
        ) : (
          <>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                    <th style={styles.th}>User</th>
                    <th style={styles.th}>Type</th>
                    <th style={styles.th}>Status</th>
                    <th style={styles.th}>Provider</th>
                    <th style={styles.th}>Vertical</th>
                    <th style={styles.th}>Cost</th>
                    <th style={styles.th}>Created</th>
                    <th style={styles.th}>Result</th>
                    <th style={styles.th}>Feedback</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job, idx) => (
                    <tr key={job.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', background: idx % 2 === 1 ? 'rgba(255,255,255,0.03)' : 'transparent' }}>
                      <td style={{ ...styles.td, maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={job.user_id || job.user_email}>
                        {job.user_email || (job.user_id ? job.user_id.slice(0, 8) + '...' : '--')}
                      </td>
                      <td style={styles.td}>{GEN_JOB_TYPE_LABELS[job.job_type] || job.job_type}</td>
                      <td style={styles.td}>
                        <span style={styles.badge(GEN_STATUS_COLORS[job.status] || 'gray')}>{job.status}</span>
                      </td>
                      <td style={styles.td}>{job.provider || '--'}</td>
                      <td style={styles.td}>{job.vertical || '--'}</td>
                      <td style={styles.td}>{job.cost_usd != null ? `$${Number(job.cost_usd).toFixed(3)}` : '--'}</td>
                      <td style={{ ...styles.td, whiteSpace: 'nowrap' }}>{new Date(job.created_at).toLocaleString()}</td>
                      <td style={styles.td}>
                        {job.status === 'completed' && job.result_url ? (
                          <a
                            href={job.result_url.startsWith('/') ? `${API_HOST}${job.result_url}` : job.result_url}
                            target="_blank" rel="noopener"
                            style={{ fontSize: '12px', color: '#2997ff' }}
                          >
                            View
                          </a>
                        ) : '--'}
                      </td>
                      <td style={styles.td}>
                        {job.admin_feedback ? (
                          <span style={styles.badge(job.admin_feedback.rating === 'positive' ? 'green' : job.admin_feedback.rating === 'negative' ? 'red' : 'gray')}>
                            {job.admin_feedback.rating}
                          </span>
                        ) : feedbackJobId === job.id ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: '180px' }}>
                            <div style={{ display: 'flex', gap: '4px' }}>
                              <button
                                onClick={() => setFeedbackRating('positive')}
                                style={{
                                  ...styles.btnSecondary,
                                  padding: '4px 10px',
                                  fontSize: '12px',
                                  background: feedbackRating === 'positive' ? 'rgba(48,209,88,0.2)' : undefined,
                                  borderColor: feedbackRating === 'positive' ? '#30d158' : undefined,
                                  color: feedbackRating === 'positive' ? '#30d158' : undefined,
                                }}
                              >
                                Good
                              </button>
                              <button
                                onClick={() => setFeedbackRating('negative')}
                                style={{
                                  ...styles.btnSecondary,
                                  padding: '4px 10px',
                                  fontSize: '12px',
                                  background: feedbackRating === 'negative' ? 'rgba(255,69,58,0.2)' : undefined,
                                  borderColor: feedbackRating === 'negative' ? '#ff6b6b' : undefined,
                                  color: feedbackRating === 'negative' ? '#ff6b6b' : undefined,
                                }}
                              >
                                Bad
                              </button>
                            </div>
                            <input
                              type="text"
                              placeholder="Comment..."
                              value={feedbackComment}
                              onChange={e => setFeedbackComment(e.target.value)}
                              style={{
                                background: 'rgba(255,255,255,0.08)',
                                border: '1px solid rgba(255,255,255,0.12)',
                                borderRadius: '4px',
                                padding: '4px 8px',
                                fontSize: '12px',
                                color: '#e8e8ed',
                              }}
                            />
                            <div style={{ display: 'flex', gap: '4px' }}>
                              <button onClick={() => submitFeedback(job.id)} style={{ ...styles.btnPrimary, padding: '4px 10px', fontSize: '11px' }}>Submit</button>
                              <button onClick={() => { setFeedbackJobId(''); setFeedbackRating(''); setFeedbackComment(''); }} style={{ ...styles.btnSecondary, padding: '4px 10px', fontSize: '11px' }}>Cancel</button>
                            </div>
                          </div>
                        ) : (
                          <button
                            onClick={() => { setFeedbackJobId(job.id); setFeedbackRating(''); setFeedbackComment(''); }}
                            style={{ ...styles.btnSecondary, padding: '4px 10px', fontSize: '11px' }}
                          >
                            Feedback
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', gap: '8px', marginTop: '16px' }}>
                <button style={styles.btnSecondary} disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button>
                <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.48)', lineHeight: '32px' }}>Page {page} of {totalPages}</span>
                <button style={styles.btnSecondary} disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AdminPanel (main)
// ---------------------------------------------------------------------------

export default function AdminPanel() {
  const [activeTab, setActiveTab] = useState<SubTab>('overview');

  const tabs: { id: SubTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'users', label: 'Users' },
    { id: 'feedback', label: 'Feedback' },
    { id: 'suggestions', label: 'AI Suggestions' },
    { id: 'learning', label: 'Learning' },
    { id: 'models', label: 'Models' },
    { id: 'generations', label: 'Generations' },
    { id: 'audit', label: 'Audit Log' },
  ];

  return (
    <div style={styles.page}>
      <div style={{ maxWidth: '1400px', margin: '0 auto' }}>
        <h1 style={{ ...styles.heading, marginBottom: '24px' }}>Admin Dashboard</h1>

        <div style={styles.tabBar}>
          {tabs.map((t) => (
            <button key={t.id} style={styles.tab(activeTab === t.id)} onClick={() => setActiveTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>

        {activeTab === 'overview' && <OverviewTab />}
        {activeTab === 'users' && <UsersTab />}
        {activeTab === 'feedback' && <FeedbackTab />}
        {activeTab === 'suggestions' && <SuggestionsTab />}
        {activeTab === 'learning' && <LearningTab />}
        {activeTab === 'models' && <ModelsTab />}
        {activeTab === 'generations' && <GenerationsTab />}
        {activeTab === 'audit' && <AuditLogTab />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audit Log Tab — full timeline of every recorded action
// ---------------------------------------------------------------------------

const AUDIT_ACTION_LABELS: Record<string, { label: string; color: string }> = {
  login_success:          { label: 'Login',           color: 'green' },
  login_failed:           { label: 'Login failed',    color: 'red' },
  logout:                 { label: 'Logout',          color: 'gray' },
  register:               { label: 'Registered',      color: 'blue' },
  user_approved:          { label: 'User approved',   color: 'green' },
  user_rejected:          { label: 'User rejected',   color: 'red' },
  user_created_by_admin:  { label: 'Admin created',   color: 'blue' },
  user_deactivated:       { label: 'Deactivated',     color: 'red' },
  user_reactivated:       { label: 'Reactivated',     color: 'green' },
  role_changed:           { label: 'Role changed',    color: 'blue' },
  api_request:            { label: 'API call',        color: 'gray' },
  page_view:              { label: 'Page view',       color: 'gray' },
  generation_started:     { label: 'Gen started',     color: 'blue' },
  generation_completed:   { label: 'Gen completed',   color: 'green' },
  generation_failed:      { label: 'Gen failed',      color: 'red' },
  download:               { label: 'Download',        color: 'gray' },
  feedback_given:         { label: 'Feedback',        color: 'blue' },
};

const AUDIT_CATEGORIES = ['auth', 'admin', 'navigation', 'generation', 'jobs', 'api'];

interface AuditEntry {
  id: string;
  timestamp: string;
  user_id: string | null;
  user_email: string | null;
  role: string | null;
  action: string;
  category: string | null;
  resource_type: string | null;
  resource_id: string | null;
  screen: string | null;
  method: string | null;
  path: string | null;
  status_code: number | null;
  duration_ms: number | null;
  ip: string | null;
  user_agent: string | null;
  metadata: Record<string, unknown> | null;
}

function AuditLogTab() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [summary, setSummary] = useState<any>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState({
    user_email: '', action: '', category: '',
    method: '', status_code: '', search: '',
    since_hours: '24',
  });
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const fetchAudit = useCallback(() => {
    setLoading(true);
    const params: Record<string, string | number> = { page, page_size: 100 };
    if (filters.user_email) params.user_email = filters.user_email;
    if (filters.action) params.action = filters.action;
    if (filters.category) params.category = filters.category;
    if (filters.method) params.method = filters.method;
    if (filters.status_code) params.status_code = filters.status_code;
    if (filters.search) params.search = filters.search;
    if (filters.since_hours) params.since_hours = filters.since_hours;

    axios.get(`${API_BASE_URL}/admin/audit-log`, { params })
      .then((r) => {
        const d = r.data?.data ?? {};
        setEntries(d.entries || []);
        setTotalPages(d.total_pages || 1);
        setTotal(d.total || 0);
      })
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, [page, filters]);

  const fetchSummary = useCallback(() => {
    const since = filters.since_hours || '24';
    axios.get(`${API_BASE_URL}/admin/audit-log/summary`, { params: { since_hours: since } })
      .then((r) => setSummary(r.data?.data))
      .catch(() => setSummary(null));
  }, [filters.since_hours]);

  useEffect(() => { fetchAudit(); }, [fetchAudit]);
  useEffect(() => { fetchSummary(); }, [fetchSummary]);

  // Live tail — re-fetch every 5s while autoRefresh is on
  useEffect(() => {
    if (!autoRefresh) return;
    const iv = setInterval(() => { fetchAudit(); fetchSummary(); }, 5000);
    return () => clearInterval(iv);
  }, [autoRefresh, fetchAudit, fetchSummary]);

  const updateFilter = (key: string, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(1);
  };
  const clearFilters = () => {
    setFilters({ user_email: '', action: '', category: '', method: '', status_code: '', search: '', since_hours: '24' });
    setPage(1);
  };

  const fmtAge = (iso: string) => {
    const ms = Date.now() - new Date(iso).getTime();
    if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
    if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
    if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
    return new Date(iso).toLocaleString();
  };

  const inputStyle: React.CSSProperties = {
    background: 'rgba(255,255,255,0.06)',
    border: '1px solid rgba(255,255,255,0.12)',
    borderRadius: '6px',
    padding: '6px 10px',
    fontSize: '13px',
    color: '#e8e8ed',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Summary cards */}
      {summary && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
          <div style={styles.card}>
            <p style={styles.statLabel}>Events ({summary.since_hours}h)</p>
            <p style={styles.statValue}>{summary.total_events ?? 0}</p>
          </div>
          <div style={styles.card}>
            <p style={styles.statLabel}>Failed Logins ({summary.since_hours}h)</p>
            <p style={{ ...styles.statValue, color: (summary.failed_logins ?? 0) > 0 ? '#ff6b6b' : '#fff' }}>
              {summary.failed_logins ?? 0}
            </p>
          </div>
          {summary.by_user?.[0] && (
            <div style={styles.card}>
              <p style={styles.statLabel}>Most Active User</p>
              <p style={{ ...styles.statValue, fontSize: '14px' }}>{summary.by_user[0].user_email}</p>
              <p style={{ ...styles.statLabel, marginTop: '4px' }}>{summary.by_user[0].count} events</p>
            </div>
          )}
          {summary.by_action?.[0] && (
            <div style={styles.card}>
              <p style={styles.statLabel}>Top Action</p>
              <p style={{ ...styles.statValue, fontSize: '14px' }}>
                {AUDIT_ACTION_LABELS[summary.by_action[0].action]?.label || summary.by_action[0].action}
              </p>
              <p style={{ ...styles.statLabel, marginTop: '4px' }}>{summary.by_action[0].count}</p>
            </div>
          )}
        </div>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <input
          placeholder="Search path, screen, email..."
          value={filters.search}
          onChange={(e) => updateFilter('search', e.target.value)}
          style={{ ...inputStyle, width: '220px' }}
        />
        <input
          placeholder="user@email"
          value={filters.user_email}
          onChange={(e) => updateFilter('user_email', e.target.value)}
          style={{ ...inputStyle, width: '180px' }}
        />
        <select value={filters.action} onChange={(e) => updateFilter('action', e.target.value)} style={styles.select}>
          <option value="">All actions</option>
          {Object.keys(AUDIT_ACTION_LABELS).map((a) => (
            <option key={a} value={a}>{AUDIT_ACTION_LABELS[a].label}</option>
          ))}
        </select>
        <select value={filters.category} onChange={(e) => updateFilter('category', e.target.value)} style={styles.select}>
          <option value="">All categories</option>
          {AUDIT_CATEGORIES.map((c) => (<option key={c} value={c}>{c}</option>))}
        </select>
        <select value={filters.method} onChange={(e) => updateFilter('method', e.target.value)} style={styles.select}>
          <option value="">All methods</option>
          {['GET', 'POST', 'PUT', 'DELETE'].map((m) => (<option key={m} value={m}>{m}</option>))}
        </select>
        <select value={filters.since_hours} onChange={(e) => updateFilter('since_hours', e.target.value)} style={styles.select}>
          <option value="1">Last 1h</option>
          <option value="24">Last 24h</option>
          <option value="168">Last 7d</option>
          <option value="720">Last 30d</option>
        </select>
        <button style={styles.btnSecondary} onClick={clearFilters}>Clear</button>
        <button
          style={autoRefresh ? styles.btnPrimary : styles.btnSecondary}
          onClick={() => setAutoRefresh((v) => !v)}
        >
          {autoRefresh ? 'Live ●' : 'Live ○'}
        </button>
        <button style={styles.btnSecondary} onClick={() => { fetchAudit(); fetchSummary(); }}>
          Refresh
        </button>
        <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.45)', marginLeft: 'auto' }}>
          {total.toLocaleString()} total
        </span>
      </div>

      {/* Table */}
      <div style={styles.card}>
        {loading ? (
          <div style={styles.spinner}>Loading audit log...</div>
        ) : entries.length === 0 ? (
          <div style={styles.empty}>No audit events match these filters.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                  <th style={styles.th}>When</th>
                  <th style={styles.th}>User</th>
                  <th style={styles.th}>Action</th>
                  <th style={styles.th}>Screen / Path</th>
                  <th style={styles.th}>Method</th>
                  <th style={styles.th}>Status</th>
                  <th style={styles.th}>Duration</th>
                  <th style={styles.th}>IP</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e, idx) => {
                  const meta = AUDIT_ACTION_LABELS[e.action] || { label: e.action, color: 'gray' };
                  const isExpanded = expanded === e.id;
                  const statusBad = (e.status_code ?? 0) >= 400;
                  return (
                    <>
                      <tr
                        key={e.id}
                        onClick={() => setExpanded(isExpanded ? null : e.id)}
                        style={{
                          borderBottom: '1px solid rgba(255,255,255,0.06)',
                          background: idx % 2 === 1 ? 'rgba(255,255,255,0.03)' : 'transparent',
                          cursor: 'pointer',
                        }}
                      >
                        <td style={{ ...styles.td, whiteSpace: 'nowrap', fontSize: '12px', color: 'rgba(255,255,255,0.6)' }}>
                          {fmtAge(e.timestamp)}
                        </td>
                        <td style={{ ...styles.td, fontSize: '12px' }}>
                          {e.user_email || <span style={{ color: 'rgba(255,255,255,0.35)' }}>anonymous</span>}
                          {e.role && (
                            <span style={{ ...styles.badge('gray'), marginLeft: '6px', fontSize: '10px' }}>{e.role}</span>
                          )}
                        </td>
                        <td style={styles.td}>
                          <span style={styles.badge(meta.color)}>{meta.label}</span>
                        </td>
                        <td style={{ ...styles.td, fontSize: '12px', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          <span style={{ color: '#2997ff' }}>{e.screen || ''}</span>
                          {e.screen && e.path && ' · '}
                          <span style={{ color: 'rgba(255,255,255,0.5)' }}>{e.path}</span>
                        </td>
                        <td style={{ ...styles.td, fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>{e.method || '--'}</td>
                        <td style={styles.td}>
                          {e.status_code ? (
                            <span style={{ ...styles.badge(statusBad ? 'red' : 'green'), fontSize: '11px' }}>{e.status_code}</span>
                          ) : '--'}
                        </td>
                        <td style={{ ...styles.td, fontSize: '11px', color: 'rgba(255,255,255,0.5)' }}>
                          {e.duration_ms != null ? `${e.duration_ms}ms` : '--'}
                        </td>
                        <td style={{ ...styles.td, fontSize: '11px', color: 'rgba(255,255,255,0.45)', fontFamily: 'monospace' }}>
                          {e.ip || '--'}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr style={{ background: 'rgba(0,0,0,0.25)' }}>
                          <td colSpan={8} style={{ padding: '12px 16px' }}>
                            <pre style={{
                              margin: 0, fontSize: '11px', color: 'rgba(255,255,255,0.7)',
                              fontFamily: 'ui-monospace, monospace', whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                            }}>{JSON.stringify({
                              id: e.id,
                              timestamp: e.timestamp,
                              category: e.category,
                              resource: e.resource_type ? { type: e.resource_type, id: e.resource_id } : undefined,
                              user_agent: e.user_agent,
                              metadata: e.metadata,
                            }, null, 2)}</pre>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {totalPages > 1 && (
          <div style={{ display: 'flex', justifyContent: 'center', gap: '8px', marginTop: '16px' }}>
            <button style={styles.btnSecondary} disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</button>
            <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.48)', lineHeight: '32px' }}>Page {page} of {totalPages}</span>
            <button style={styles.btnSecondary} disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next</button>
          </div>
        )}
      </div>
    </div>
  );
}
