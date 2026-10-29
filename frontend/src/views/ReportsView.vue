<template>
  <div>
    <section class="page-heading">
      <div>
        <span class="eyebrow">AP AUTOMATION</span>
        <h1>Reports & Analytics Hub</h1>
        <p class="subtitle">Real-time financial audits, budget trackers, tax compliance, and bank disbursal logs.</p>
      </div>
    </section>

    <!-- Report Cards Grid (Matching Design System) -->
    <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 18px;">
      <article
        v-for="rep in reportList"
        :key="rep.slug"
        style="padding: 22px; border: 1px solid #e7e8f8; border-radius: 20px; background: rgba(255, 255, 255, 0.92); box-shadow: var(--shadow); cursor: pointer; transition: 0.2s;"
        @click="$router.push(`/reports/${rep.slug}`)"
      >
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px;">
          <div class="kpi-icon" :class="rep.color" style="width: 44px; height: 44px; font-size: 20px; border-radius: 14px;">
            {{ rep.icon }}
          </div>
          <span style="font-size: 10px; font-weight: 800; color: var(--purple-dark); background: #eee9ff; padding: 4px 10px; border-radius: 999px;">
            {{ rep.tag }}
          </span>
        </div>
        <h3 style="margin: 0 0 8px; font-size: 14px; font-weight: 800; color: var(--ink);">{{ rep.title }}</h3>
        <p style="margin: 0 0 16px; color: var(--muted); font-size: 11px; line-height: 1.55;">{{ rep.description }}</p>
        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #f0f1fa; padding-top: 14px; font-size: 11px; font-weight: 700; color: var(--purple);">
          <router-link :to="`/reports/${rep.slug}`" style="color: inherit; text-decoration: none;">Generate Report</router-link>
          <span style="font-size: 14px;">→</span>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup>
const emit = defineEmits(['toast']);

const reportList = [
  {
    slug: 'vendor_p2p',
    title: 'Vendor Payment & P2P 360 Report',
    description: 'Turnaround time (TAT) per approver level, TDS statutory deductions, and vendor spend analysis.',
    tag: 'Compliance',
    icon: '▤',
    color: 'amber',
  },
  {
    slug: 'idfc_disbursal',
    title: 'IDFC Bank Disbursal Audit Report',
    description: 'Historical records of Friday bank batches with bank UTR reference timestamps and status.',
    tag: 'Banking',
    icon: '▣',
    color: 'purple',
  },
  {
    slug: 'employee_360',
    title: 'Employee Spend & Pre-Travel 360 Report',
    description: 'Zero-advance travel audit, mileage reimbursement logs, and fast-track policy compliance.',
    tag: 'HRMS Spend',
    icon: '♙',
    color: 'green',
  },
  {
    slug: 'petty_cash',
    title: 'Petty Cash Summary Report',
    description: 'Branch-level custodian balances, weekly replenishment requests, and voucher audit trail.',
    tag: 'Treasury',
    icon: '▦',
    color: 'red',
  },
  {
    slug: 'event_spends',
    title: 'Event Spends & Budget Tracker (Live Ledger 360)',
    description: 'Tracks Stream A direct spends, SPOC advances, ground actuals, overrun variance and 30-day ageing alerts.',
    tag: 'Live Ledger',
    icon: '◉',
    color: 'purple',
  },
  {
    slug: 'gst_tds',
    title: 'GST & Statutory TDS Audit Report',
    description: 'Section 194C, 194J, 194Q tax deduction register for monthly GSTR-2B matching and filing.',
    tag: 'Tax Audit',
    icon: '✓',
    color: 'green',
  },
];
</script>
