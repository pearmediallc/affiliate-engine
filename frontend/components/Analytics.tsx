'use client';

import { useState, useEffect } from 'react';
import { fetchBilling } from '@/lib/api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export default function Analytics({ data }: { data: any }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [billing, setBilling] = useState<any>(null);
  const [billingError, setBillingError] = useState('');

  useEffect(() => {
    fetchBilling()
      .then(setBilling)
      .catch(() => setBillingError('Failed to load billing data'));
  }, []);

  if (!data) {
    return (
      <div className="card text-center py-12">
        <p className="text-gray-500">No analytics data available yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Key Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="card">
          <p className="text-gray-600 text-sm">Total Images</p>
          <p className="text-4xl font-bold text-gray-900 mt-2">
            {data.total_images || 0}
          </p>
        </div>

        <div className="card">
          <p className="text-gray-600 text-sm">Total Cost</p>
          <p className="text-4xl font-bold text-blue-600 mt-2">
            ${(data.total_cost || 0).toFixed(2)}
          </p>
        </div>

        <div className="card">
          <p className="text-gray-600 text-sm">Total Revenue</p>
          <p className="text-4xl font-bold text-green-600 mt-2">
            ${(data.total_revenue || 0).toFixed(2)}
          </p>
        </div>

        <div className="card">
          <p className="text-gray-600 text-sm">ROI</p>
          <p className="text-4xl font-bold text-purple-600 mt-2">
            {(data.roi_percent || 0).toFixed(1)}%
          </p>
        </div>
      </div>

      {/* Campaign Performance */}
      <div className="card">
        <h3 className="text-xl font-bold mb-6">Campaign Performance</h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div>
            <div className="flex items-baseline space-x-2 mb-2">
              <p className="text-3xl font-bold text-gray-900">
                {data.total_clicks || 0}
              </p>
              <p className="text-gray-600">clicks</p>
            </div>
            <p className="text-sm text-gray-500">Total campaign clicks</p>
          </div>

          <div>
            <div className="flex items-baseline space-x-2 mb-2">
              <p className="text-3xl font-bold text-gray-900">
                {data.total_conversions || 0}
              </p>
              <p className="text-gray-600">conversions</p>
            </div>
            <p className="text-sm text-gray-500">Total conversions</p>
          </div>

          <div>
            <div className="flex items-baseline space-x-2 mb-2">
              <p className="text-3xl font-bold text-gray-900">
                {(data.average_ctr || 0).toFixed(2)}%
              </p>
              <p className="text-gray-600">CTR</p>
            </div>
            <p className="text-sm text-gray-500">Average click-through rate</p>
          </div>
        </div>
      </div>

      {/* Billing & Spend */}
      {billingError && (
        <div className="card bg-red-50">
          <p className="text-red-700 text-sm">{billingError}</p>
        </div>
      )}
      {billing && (
        <div className="space-y-6">
          <h3 className="text-2xl font-bold text-gray-900">Billing &amp; Spend</h3>

          {/* Total Spend */}
          <div className="card bg-gradient-to-r from-blue-600 to-indigo-600 text-white">
            <p className="text-sm opacity-80">Total Spend</p>
            <p className="text-5xl font-bold mt-2">
              ${(billing.total_spent || 0).toFixed(4)}
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Per-Provider Breakdown */}
            <div className="card">
              <h4 className="text-lg font-bold mb-4">By Provider</h4>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-2 text-gray-600">Provider</th>
                    <th className="text-right py-2 text-gray-600">Count</th>
                    <th className="text-right py-2 text-gray-600">Total Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  {billing.by_provider?.map((row: any) => (
                    <tr key={row.provider} className="border-b border-gray-100">
                      <td className="py-2 font-medium capitalize">{row.provider}</td>
                      <td className="py-2 text-right">{row.count}</td>
                      <td className="py-2 text-right">${row.total_cost.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Per-Model Breakdown */}
            <div className="card">
              <h4 className="text-lg font-bold mb-4">By Model</h4>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-2 text-gray-600">Model</th>
                    <th className="text-right py-2 text-gray-600">Count</th>
                    <th className="text-right py-2 text-gray-600">Total Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  {billing.by_model?.map((row: any) => (
                    <tr key={row.model} className="border-b border-gray-100">
                      <td className="py-2 font-medium">{row.model}</td>
                      <td className="py-2 text-right">{row.count}</td>
                      <td className="py-2 text-right">${row.total_cost.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Recent Generations */}
          <div className="card">
            <h4 className="text-lg font-bold mb-4">Recent Generations</h4>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-2 text-gray-600">Provider</th>
                    <th className="text-left py-2 text-gray-600">Model</th>
                    <th className="text-right py-2 text-gray-600">Cost</th>
                    <th className="text-left py-2 text-gray-600">Vertical</th>
                    <th className="text-left py-2 text-gray-600">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  {billing.recent_generations?.map((row: any) => (
                    <tr key={row.id} className="border-b border-gray-100">
                      <td className="py-2 capitalize">{row.provider}</td>
                      <td className="py-2">{row.model || '-'}</td>
                      <td className="py-2 text-right">${row.cost.toFixed(4)}</td>
                      <td className="py-2">{row.vertical}</td>
                      <td className="py-2 text-gray-500">
                        {row.created_at
                          ? new Date(row.created_at).toLocaleDateString()
                          : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Performance Insights */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Status Summary */}
        <div className="card">
          <h3 className="text-xl font-bold mb-4">Status Summary</h3>

          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-gray-700">Generation Status</span>
              <span className="px-3 py-1 bg-green-100 text-green-800 rounded-full text-sm font-medium">
                Active
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-gray-700">Total Spend</span>
              <span className="font-medium">
                ${(data.total_cost || 0).toFixed(2)}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-gray-700">Images Generated</span>
              <span className="font-medium">{data.total_images || 0}</span>
            </div>

            <div className="flex items-center justify-between pt-3 border-t border-gray-200">
              <span className="text-gray-700 font-medium">Estimated Value</span>
              <span className="font-bold text-lg text-green-600">
                ${(data.total_revenue || 0).toFixed(2)}
              </span>
            </div>
          </div>
        </div>

        {/* Recommendations */}
        <div className="card bg-blue-50">
          <h3 className="text-xl font-bold text-blue-900 mb-4">💡 Recommendations</h3>

          <ul className="space-y-3">
            <li className="flex space-x-3">
              <span className="text-blue-600 font-bold flex-shrink-0">1</span>
              <span className="text-gray-700 text-sm">
                Keep testing high-CTR templates consistently
              </span>
            </li>

            <li className="flex space-x-3">
              <span className="text-blue-600 font-bold flex-shrink-0">2</span>
              <span className="text-gray-700 text-sm">
                Track which ad copy works best with each template
              </span>
            </li>

            <li className="flex space-x-3">
              <span className="text-blue-600 font-bold flex-shrink-0">3</span>
              <span className="text-gray-700 text-sm">
                Consider state-specific variations for better targeting
              </span>
            </li>

            <li className="flex space-x-3">
              <span className="text-blue-600 font-bold flex-shrink-0">4</span>
              <span className="text-gray-700 text-sm">
                Monitor conversion rates and adjust templates accordingly
              </span>
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
