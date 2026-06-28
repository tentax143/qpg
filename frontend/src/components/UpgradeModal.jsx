'use client';

import { useState, useEffect } from 'react';
import { X, CheckCircle, Loader2, Zap, ArrowRight, TrendingUp } from 'lucide-react';
import apiClient from '@/lib/api';

const PLAN_FEATURES = {
  free:   ['5 papers / month', '2 teachers', 'All subjects'],
  basic:  ['30 papers / month', '5 teachers', 'All subjects', 'Email support'],
  pro:    ['100 papers / month', '15 teachers', 'All subjects', 'Chat support'],
  school: ['Unlimited papers', 'Unlimited teachers', 'All subjects', 'Priority support'],
};

const PLAN_ORDER = ['free', 'basic', 'pro', 'school'];

// reason: 'paper' | 'teacher'
export default function UpgradeModal({ onClose, reason = 'paper', onSuccess }) {
  const [plans, setPlans]     = useState([]);
  const [current, setCurrent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [upgrading, setUpgrading] = useState('');
  const [error, setError]     = useState('');

  useEffect(() => {
    Promise.all([
      apiClient.get('/billing/plans/'),
      apiClient.get('/billing/status/'),
    ]).then(([plansRes, statusRes]) => {
      setPlans(plansRes.data);
      setCurrent(statusRes.data);
    }).catch(() => setError('Could not load plans.')).finally(() => setLoading(false));
  }, []);

  const currentIdx = PLAN_ORDER.indexOf(current?.plan_key || 'free');

  const heading = reason === 'teacher' ? 'Teacher Limit Reached' : 'Paper Limit Reached';

  const subtext = !current ? '' : reason === 'teacher'
    ? `Your school has reached its teacher limit on the ${current.plan_name} plan. Upgrade to add more teachers.`
    : `Your school has used all ${current.paper_limit_unlimited ? '∞' : current.paper_limit} papers this month on the ${current.plan_name} plan. Upgrade to generate more.`;

  async function handleUpgrade(planName, planDisplay) {
    setUpgrading(planName);
    setError('');
    try {
      const res = await apiClient.post('/billing/create-order/', { plan_name: planName });
      const { order_id, amount, currency, plan_display } = res.data;
      const keyId = current?.razorpay_key_id || res.data.razorpay_key_id;

      if (!keyId) {
        setError('Payment gateway not configured. Contact the administrator.');
        setUpgrading('');
        return;
      }

      if (!window.Razorpay) {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = 'https://checkout.razorpay.com/v1/checkout.js';
          s.onload = resolve;
          s.onerror = reject;
          document.body.appendChild(s);
        });
      }

      const options = {
        key: keyId,
        amount,
        currency,
        name: 'Shiken',
        description: `${plan_display || planDisplay} Plan (Monthly)`,
        order_id,
        handler: async (response) => {
          try {
            await apiClient.post('/billing/verify-payment/', {
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            });
            onSuccess?.(planName);
            onClose();
          } catch {
            setError('Payment received but activation failed. Contact support.');
          }
        },
        theme: { color: '#2563eb' },
        modal: { ondismiss: () => setUpgrading('') },
      };

      const rzp = new window.Razorpay(options);
      rzp.open();
    } catch (e) {
      setError(e.response?.data?.error || 'Could not initiate payment.');
      setUpgrading('');
    }
  }

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-gray-900/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="relative bg-white rounded-3xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto z-10 animate-in fade-in zoom-in-95 duration-300">
        {/* Header */}
        <div className="p-6 border-b border-gray-100 flex items-start justify-between gap-4 bg-gradient-to-r from-amber-50 to-orange-50 rounded-t-3xl">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 bg-amber-100 rounded-2xl flex items-center justify-center shadow-sm">
              <TrendingUp className="w-5 h-5 text-amber-600" />
            </div>
            <div>
              <h2 className="text-lg font-black text-gray-900 tracking-tight">{heading}</h2>
              {!loading && current && (
                <p className="text-sm text-gray-500 mt-0.5 max-w-md">{subtext}</p>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-xl flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-white transition-colors shrink-0"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="p-6">
          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
            </div>
          ) : error && !plans.length ? (
            <p className="text-red-600 text-sm text-center py-8">{error}</p>
          ) : (
            <>
              {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
                  {error}
                </div>
              )}

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {plans.map((plan) => {
                  const idx       = PLAN_ORDER.indexOf(plan.name);
                  const isCurrent = current?.plan_key === plan.name;
                  const isBelow   = idx < currentIdx;
                  const isAbove   = idx > currentIdx;
                  const isBusy    = upgrading === plan.name;
                  const isPopular = plan.name === 'pro';
                  const features  = PLAN_FEATURES[plan.name] || [];
                  const canUpgrade = isAbove && plan.name !== 'free';

                  return (
                    <div
                      key={plan.name}
                      className={`relative rounded-2xl border p-4 flex flex-col gap-3 transition-all duration-200
                        ${isPopular && isAbove ? 'border-blue-400 shadow-lg bg-blue-50/20' : 'border-gray-200 bg-white'}
                        ${isCurrent || isBelow ? 'opacity-50' : ''}
                      `}
                    >
                      {isPopular && isAbove && (
                        <div className="absolute -top-2.5 left-1/2 -translate-x-1/2">
                          <span className="bg-blue-600 text-white text-[10px] font-semibold px-2.5 py-0.5 rounded-full whitespace-nowrap">
                            Recommended
                          </span>
                        </div>
                      )}

                      <div>
                        <p className="font-black text-gray-900 text-sm">{plan.display_name}</p>
                        <p className="text-xl font-black text-gray-900 mt-0.5 leading-tight">
                          {plan.price_inr === '0.00'
                            ? 'Free'
                            : `₹${Number(plan.price_inr).toLocaleString('en-IN')}`}
                          {plan.price_inr !== '0.00' && (
                            <span className="text-xs font-normal text-gray-400">/mo</span>
                          )}
                        </p>
                      </div>

                      <ul className="flex-1 space-y-1.5">
                        {features.map(f => (
                          <li key={f} className="flex items-start gap-1.5 text-xs text-gray-600">
                            <CheckCircle className="w-3 h-3 text-green-500 mt-0.5 shrink-0" />
                            {f}
                          </li>
                        ))}
                      </ul>

                      <button
                        disabled={!canUpgrade || isBusy || isCurrent}
                        onClick={() => canUpgrade && handleUpgrade(plan.name, plan.display_name)}
                        className={`w-full py-2.5 rounded-xl text-xs font-black uppercase tracking-wider transition-colors flex items-center justify-center gap-1.5
                          ${isCurrent
                            ? 'bg-green-100 text-green-700 cursor-default'
                            : isBelow || plan.name === 'free'
                            ? 'bg-gray-100 text-gray-400 cursor-default'
                            : isPopular
                            ? 'bg-blue-600 hover:bg-blue-700 text-white shadow-md shadow-blue-200'
                            : 'bg-slate-800 hover:bg-slate-900 text-white'
                          }`}
                      >
                        {isBusy && <Loader2 className="w-3 h-3 animate-spin" />}
                        {isCurrent
                          ? 'Current'
                          : isBelow || plan.name === 'free'
                          ? 'N/A'
                          : <><Zap size={11} /> Upgrade</>}
                      </button>
                    </div>
                  );
                })}
              </div>

              <p className="text-xs text-gray-400 text-center mt-5">
                Payments processed securely via Razorpay · GST invoice by email · Cancel anytime
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
