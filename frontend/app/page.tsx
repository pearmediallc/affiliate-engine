'use client';

import { useEffect, useState } from 'react';
import Dashboard from '@/components/Dashboard';
import { fetchTemplates, fetchAnalytics } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import LoginPage from '@/components/LoginPage';

export default function Home() {
  const { user, loading: authLoading } = useAuth();
  const [vertical, setVertical] = useState('home_insurance');
  const [templates, setTemplates] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!user) {
      setLoading(false);
      return;
    }
    const loadData = async () => {
      try {
        setLoading(true);
        const templatesData = await fetchTemplates(vertical);
        setTemplates(templatesData.templates || []);

        const analyticsData = await fetchAnalytics();
        setAnalytics(analyticsData);
      } catch (err) {
        console.error('Error loading data:', err);
        setError('Failed to load data');
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [vertical, user]);

  if (authLoading) {
    return (
      <div style={{ minHeight: '100vh', backgroundColor: '#f5f5f7', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <p style={{ color: 'rgba(0,0,0,0.48)', fontSize: '17px' }}>Loading...</p>
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <Dashboard
      templates={templates}
      analytics={analytics}
      error={error}
      vertical={vertical}
      onVerticalChange={setVertical}
    />
  );
}
