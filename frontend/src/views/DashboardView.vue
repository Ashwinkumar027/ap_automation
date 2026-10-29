<template>
  <div>
    <section class="page-heading">
      <div>
        <span class="eyebrow">AP AUTOMATION</span>
        <h1>Executive Dashboard</h1>
        <p class="subtitle">Real-time Accounts Payable operational overview, cash burn, and pending approval queues.</p>
      </div>
      <button class="primary-btn" @click="emitToast('Exporting executive spend summary...')">
        <span>⇩</span> Download Executive Summary
      </button>
    </section>

    <!-- Main KPIs -->
    <section class="kpis">
      <KpiCard icon="₹" color="purple" value="₹ 48.5L" label="Total Invoiced (MTD)" trend="↗ +15% vs last month" spark-color="#7655ff" />
      <KpiCard icon="◷" color="amber" value="₹ 14.2L" label="Pending Approvals" trend="38 Pending Invoices" spark-color="#f0a000" />
      <KpiCard icon="✓" color="green" value="₹ 31.8L" label="Disbursed via IDFC" trend="100% On-time Payouts" spark-color="#05bd88" />
      <KpiCard icon="!" color="red" value="₹ 2.5L" label="Disputed & Blocked" trend="4 Invoices Under Audit" trend-color="#e43f50" spark-color="#ff6676" />
    </section>

    <!-- Visual Breakdown Cards -->
    <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-top: 16px;">
      <div style="padding: 20px; border: 1px solid #e7e8f8; border-radius: 19px; background: rgba(255,255,255,0.9); box-shadow: var(--shadow);">
        <h3 style="margin: 0 0 14px; font-size: 14px; font-weight: 800;">Monthly Spend Trajectory</h3>
        <div style="height: 180px; display: flex; align-items: flex-end; gap: 20px; padding-top: 20px; border-bottom: 1px solid #eceef8;">
          <div v-for="m in monthlyData" :key="m.month" style="flex: 1; display: flex; flex-direction: column; align-items: center; gap: 8px;">
            <span style="font-size: 10px; font-weight: 700; color: var(--purple-dark)">{{ m.val }}L</span>
            <div :style="{ height: `${m.val * 3.5}px` }" style="width: 100%; border-radius: 8px 8px 0 0; background: linear-gradient(180deg, #704cff, #a996ff); transition: height 0.3s;"></div>
            <span style="font-size: 10px; color: var(--muted)">{{ m.month }}</span>
          </div>
        </div>
      </div>

      <div style="padding: 20px; border: 1px solid #e7e8f8; border-radius: 19px; background: rgba(255,255,255,0.9); box-shadow: var(--shadow);">
        <h3 style="margin: 0 0 14px; font-size: 14px; font-weight: 800;">Spend by Category</h3>
        <div style="display: flex; flex-direction: column; gap: 12px; margin-top: 10px;">
          <div v-for="c in categories" :key="c.name">
            <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 4px;">
              <span style="font-weight: 700;">{{ c.name }}</span>
              <span style="color: var(--muted)">{{ c.pct }}%</span>
            </div>
            <div class="progress" :class="c.color">
              <span :style="{ width: `${c.pct}%` }"></span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const emit = defineEmits(['toast']);
function emitToast(msg) { emit('toast', msg); }

const monthlyData = [
  { month: 'Jun', val: 28 },
  { month: 'Jul', val: 34 },
  { month: 'Aug', val: 42 },
  { month: 'Sep', val: 39 },
  { month: 'Oct', val: 48 },
];

const categories = [
  { name: 'Events & Hospitality', pct: 42, color: 'approved' },
  { name: 'IT Infrastructure & Software', pct: 28, color: 'pending' },
  { name: 'Employee Travel Reimbursements', pct: 18, color: 'approved' },
  { name: 'Marketing & Production', pct: 12, color: 'disputed' },
];
</script>

