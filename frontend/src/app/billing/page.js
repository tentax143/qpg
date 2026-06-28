'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { CheckCircle, Zap, Loader2 } from 'lucide-react';
import apiClient from '@/lib/api';

const PLAN_FEATURES = {
  free:   ['5 papers / month', '2 teachers', 'All subjects', 'Email support'],
  basic:  ['30 papers / month', '5 teachers', 'All subjects', 'Email support'],
  pro:    ['100 papers / month', '15 teachers', 'All subjects', 'Chat support'],
  school: ['Unlimited papers', 'Unlimited teachers', 'All subjects', 'Priority phone support'],
};

export default function BillingPage() {
  const router = useRouter();
  const [plans, setPlans] = useState([]);
  const [current, setCurrent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [upgrading, setUpgrading] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    const userData = localStorage.getItem('user');
    if (!userData) { router.replace('/'); return; }
    const user = JSON.parse(userData);
    if (user?.role !== 'school_admin' && user?.role !== 'superadmin') {
      router.replace('/dashboard'); return;
    }

    Promise.all([
      apiClient.get('/billing/plans/'),
      apiClient.get('/billing/status/'),
    ]).then(([plansRes, statusRes]) => {
      setPlans(plansRes.data);
      setCurrent(statusRes.data);
    }).catch(() => setError('Could not load billing info.')).finally(() => setLoading(false));
  }, []);

  async function handleUpgrade(planName, priceInr, razorpayKeyId) {
    if (planName === 'free') return;
    setUpgrading(planName); setError('');
    try {
      const res = await apiClient.post('/billing/create-order/', { plan_name: planName });
      const { order_id, amount, currency, plan_display } = res.data;
      const keyId = razorpayKeyId || res.data.razorpay_key_id || current?.razorpay_key_id || '';

      if (!keyId) {
        setError('Razorpay is not configured yet. Contact the administrator.');
        setUpgrading(''); return;
      }

      const options = {
        key: keyId,
        amount,
        currency,
        name: 'Shiken',
        description: `${plan_display} Plan (Monthly)`,
        order_id,
        handler: async (response) => {
          try {
            await apiClient.post('/billing/verify-payment/', {
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            });
            // Refresh billing status
            const updated = await apiClient.get('/billing/status/');
            setCurrent(updated.data);
            alert(`Successfully upgraded to ${plan_display}!`);
          } catch {
            setError('Payment received but activation failed. Contact support.');
          }
        },
        prefill: {},
        theme: { color: '#2563eb' },
        modal: { ondismiss: () => setUpgrading('') },
      };

      // Load Razorpay script dynamically
      if (!window.Razorpay) {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = 'https://checkout.razorpay.com/v1/checkout.js';
          s.onload = resolve; s.onerror = reject;
          document.body.appendChild(s);
        });
      }
      const rzp = new window.Razorpay(options);
      rzp.open();
    } catch (e) {
      setError(e.response?.data?.error || 'Could not initiate payment.');
    } finally {
      setUpgrading('');
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
      </div>
    );
  }

  return (
    <div className="space-y-8 max-w-4xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Billing &amp; Plans</h1>
        <p className="text-slate-500 text-sm mt-1">
          {current ? (
            <>
              You are on the <strong>{current.plan_name}</strong> plan
              {current.is_on_trial && current.trial_ends_at && (
                <span className="text-amber-600 ml-1">
                  (trial ends {new Date(current.trial_ends_at).toLocaleDateString('en-IN')})
                </span>
              )}
              · {current.papers_this_month} / {current.paper_limit_unlimited ? '∞' : current.paper_limit} papers used this month
            </>
          ) : 'Choose a plan for your school.'}
        </p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-sm">{error}</div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {plans.map(plan => {
          const isCurrent = current?.plan_key === plan.name;
          const features = PLAN_FEATURES[plan.name] || [];
          const isPopular = plan.name === 'pro';
          const isBusy = upgrading === plan.name;

          return (
            <div key={plan.name} className={`relative bg-white border rounded-2xl p-5 flex flex-col
              ${isPopular ? 'border-blue-500 shadow-md' : 'border-slate-200'}
              ${isCurrent ? 'ring-2 ring-green-400' : ''}`}>

              {isPopular && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                  <span className="bg-blue-600 text-white text-[11px] font-semibold px-3 py-0.5 rounded-full">
                    Most Popular
                  </span>
                </div>
              )}

              {isCurrent && (
                <div className="absolute -top-3 right-4">
                  <span className="bg-green-500 text-white text-[11px] font-semibold px-3 py-0.5 rounded-full flex items-center gap-1">
                    <CheckCircle className="w-3 h-3" /> Current
                  </span>
                </div>
              )}

              <div className="mb-4">
                <p className="font-bold text-slate-900 text-lg">{plan.display_name}</p>
                <p className="text-2xl font-bold text-slate-900 mt-1">
                  {plan.price_inr === '0.00' ? 'Free' : `₹${Number(plan.price_inr).toLocaleString('en-IN')}`}
                  {plan.price_inr !== '0.00' && <span className="text-sm font-normal text-slate-400">/month</span>}
                </p>
              </div>

              <ul className="space-y-1.5 flex-1 mb-5">
                {features.map(f => (
                  <li key={f} className="flex items-start gap-1.5 text-sm text-slate-600">
                    <CheckCircle className="w-3.5 h-3.5 text-green-500 mt-0.5 flex-shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>

              <button
                disabled={isCurrent || plan.name === 'free' || isBusy}
                onClick={() => handleUpgrade(plan.name, plan.price_inr, current?.razorpay_key_id)}
                className={`w-full py-2 rounded-lg text-sm font-semibold transition-colors flex items-center justify-center gap-2
                  ${isCurrent
                    ? 'bg-green-100 text-green-700 cursor-default'
                    : plan.name === 'free'
                    ? 'bg-slate-100 text-slate-400 cursor-default'
                    : isPopular
                    ? 'bg-blue-600 hover:bg-blue-700 text-white'
                    : 'bg-slate-800 hover:bg-slate-900 text-white'
                  }`}
              >
                {isBusy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {isCurrent ? 'Current plan' : plan.name === 'free' ? 'Free' : plan.name === 'school' ? 'Contact us' : `Upgrade to ${plan.display_name}`}
              </button>
            </div>
          );
        })}
      </div>

      <p className="text-xs text-slate-400 text-center">
        Payments are processed securely via Razorpay. GST invoice sent to your registered email.
        For annual billing or district-wide plans, contact us directly.
      </p>
    </div>
  );
}
