'use client';

import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import axios from 'axios';

function getApiUrl() {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== 'undefined' && window.location.hostname !== 'localhost') {
    return 'https://affiliate-engine-pl4p.onrender.com/api/v1';
  }
  return 'http://localhost:8000/api/v1';
}
const API_URL = getApiUrl();

interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  permissions: Record<string, { allowed: boolean; daily_limit?: number | null }>;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  /**
   * Register a user. Returns a result object:
   *   { approval_required: false } → user is logged in, redirect to app
   *   { approval_required: true }  → registration is pending admin approval; show banner.
   */
  register: (email: string, password: string, fullName?: string) => Promise<{ approval_required: boolean; status: string }>;
  logout: () => void;
  hasPermission: (feature: string) => boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check for stored token on mount
    const storedToken = localStorage.getItem('auth_token');
    if (storedToken) {
      setToken(storedToken);
      // Validate token by fetching profile
      axios.get(`${API_URL}/auth/me`, {
        headers: { Authorization: `Bearer ${storedToken}` }
      })
      .then(res => {
        if (res.data.success) {
          setUser(res.data.data);
        } else {
          localStorage.removeItem('auth_token');
        }
      })
      .catch(() => {
        localStorage.removeItem('auth_token');
      })
      .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  // Set up axios interceptor for auth header
  useEffect(() => {
    const interceptor = axios.interceptors.request.use(config => {
      const t = localStorage.getItem('auth_token');
      if (t) {
        config.headers.Authorization = `Bearer ${t}`;
      }
      return config;
    });
    return () => axios.interceptors.request.eject(interceptor);
  }, []);

  const login = async (email: string, password: string) => {
    const res = await axios.post(`${API_URL}/auth/login`, { email, password });
    if (res.data.success) {
      const { user: userData, access_token } = res.data.data;
      setUser(userData);
      setToken(access_token);
      localStorage.setItem('auth_token', access_token);
    } else {
      throw new Error(res.data.message || 'Login failed');
    }
  };

  const register = async (email: string, password: string, fullName?: string) => {
    const res = await axios.post(`${API_URL}/auth/register`, {
      email, password, full_name: fullName
    });
    if (!res.data.success) {
      throw new Error(res.data.message || 'Registration failed');
    }
    const data = res.data.data || {};
    // First user (auto-approved) gets a token immediately.
    if (data.access_token) {
      setUser(data.user);
      setToken(data.access_token);
      localStorage.setItem('auth_token', data.access_token);
      return { approval_required: false, status: data.status || 'approved' };
    }
    // Otherwise the user is pending admin approval — caller should show banner.
    return { approval_required: true, status: data.status || 'pending' };
  };

  const logout = () => {
    setUser(null);
    setToken(null);
    localStorage.removeItem('auth_token');
  };

  const hasPermission = (feature: string) => {
    if (!user || !user.permissions) return false;
    return user.permissions[feature]?.allowed ?? false;
  };

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout, hasPermission }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
