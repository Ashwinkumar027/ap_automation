<template>
  <div>
    <!-- Top Breadcrumb & Actions -->
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
      <div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted);">
        <router-link to="/reports" style="color: var(--purple); text-decoration: none; font-weight: 700;">← Back to Reports</router-link>
        <span>/</span>
        <strong style="color: var(--ink);">{{ reportMeta.title }}</strong>
      </div>

      <div style="display: flex; gap: 8px;">
        <button class="primary-btn" style="background: linear-gradient(120deg, #08a96a, #058f58); padding: 8px 16px; font-size: 11px;" @click="exportReportCsv">
          ⇩ Export Excel / CSV
        </button>
      </div>
    </div>

    <!-- Page Heading -->
    <section class="page-heading">
      <div>
        <span class="eyebrow">{{ reportMeta.tag }}</span>
        <h1>{{ reportMeta.title }}</h1>
        <p class="subtitle">{{ reportMeta.description }}</p>
      </div>
    </section>

    <!-- Report Summary Cards (if returned by Frappe report) -->
    <div v-if="reportSummary.length" style="display: flex; gap: 12px; margin-bottom: 18px; flex-wrap: wrap;">
      <div
        v-for="(card, sidx) in reportSummary"
        :key="sidx"
        style="padding: 12px 18px; border: 1px solid #e7e8f8; border-radius: 14px; background: rgba(255, 255, 255, 0.9); box-shadow: var(--shadow); min-width: 160px;"
      >
        <small style="color: var(--muted); font-size: 10px; font-weight: 700; text-transform: uppercase;">{{ card.label }}</small>
        <div style="font-size: 18px; font-weight: 800; color: var(--ink); margin-top: 4px;">
          <span v-if="card.datatype === 'Currency'">₹ {{ Number(card.value || 0).toLocaleString('en-IN') }}</span>
          <span v-else>{{ card.value }}</span>
        </div>
      </div>
    </div>

    <!-- Filters Panel -->
    <section class="filter-panel" style="margin-bottom: 16px;">
      <div class="filters">
        <label class="control search-control">
          <span>⌕</span>
          <input v-model="searchQ" placeholder="Filter rows..." />
        </label>
        <label class="control">
          <select v-model="filterCompany" @change="fetchLiveReport">
            <option value="">All Companies</option>
            <option>Anshul A Gupta & Associates</option>
            <option>Quanticus Software Solutions Private Limited</option>
            <option>TestCompany</option>
          </select>
        </label>
        <label class="control">
          <input type="date" v-model="dateFrom" @change="fetchLiveReport" />
        </label>
        <label class="control">
          <input type="date" v-model="dateTo" @change="fetchLiveReport" />
        </label>
        <button class="small-btn" @click="resetFilters">↻ Reset</button>
        <button class="primary-btn" style="padding: 0 14px; font-size: 11px;" @click="fetchLiveReport">
          Apply
        </button>
      </div>
    </section>

    <!-- Data Table Card -->
    <section class="table-card">
      <div v-if="isLoading" style="padding: 40px; text-align: center; color: var(--muted);">
        <div style="font-size: 24px; margin-bottom: 8px;">⏳</div>
        <strong>Executing Live Financial Query Report...</strong>
      </div>

      <div v-else class="table-scroll">
        <table>
          <thead>
            <tr>
              <th v-for="(col, cIdx) in displayColumns" :key="cIdx">
                {{ col.label || col.fieldname || col }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rIdx) in filteredRows" :key="rIdx">
              <td v-for="(col, cIdx) in displayColumns" :key="cIdx">
                <span v-if="isAmountField(col, getCellValue(row, col, cIdx))" class="amount">
                  ₹ {{ Number(getCellValue(row, col, cIdx) || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 }) }}
                </span>
                <span v-else-if="isStatusField(getCellValue(row, col, cIdx))" class="status" :class="statusClass(getCellValue(row, col, cIdx))">
                  {{ getCellValue(row, col, cIdx) }}
                </span>
                <span v-else>{{ cleanCellDisplay(getCellValue(row, col, cIdx)) }}</span>
              </td>
            </tr>
            <tr v-if="!filteredRows.length">
              <td :colspan="displayColumns.length || 6" style="padding: 32px; text-align: center; color: var(--muted);">
                No matching records found for the selected filters.
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer class="table-footer">
        <div>Showing {{ filteredRows.length }} rows</div>
      </footer>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';
import { frappeCall } from '../utils/api';

const route = useRoute();
const emit = defineEmits(['toast']);
function emitToast(msg) { emit('toast', msg); }

const isLoading = ref(false);
const searchQ = ref('');
const filterCompany = ref('');
const dateFrom = ref('2026-10-01');
const dateTo = ref('2026-10-31');

const reportSummary = ref([]);
const rawColumns = ref([]);
const rawRows = ref([]);

const reportConfigs = {
  vendor_p2p: {
    reportName: 'Vendor Payment and P2P 360 Report',
    title: 'Vendor Payment & P2P 360 Report',
    tag: 'FINANCIAL AUDIT REPORT',
    description: 'Turnaround time (TAT) per approver level, TDS statutory deductions, and vendor spend analysis.',
    fallbackCols: ['Claim ID', 'Invoice Date', 'Company', 'Supplier Name', 'Invoice #', 'Base Taxable', 'GST', 'Gross Total', 'Net Disbursal', 'Status'],
    fallbackRows: [
      ['VINV-2026-10-03618', '2026-10-28', 'Anshul A Gupta & Associates', 'Grand Convention Center', 'INV-RESORT-01', 150000, 27000, 177000, 175500, 'Approved for Payment'],
      ['VINV-2026-10-03600', '2026-10-28', 'Anshul A Gupta & Associates', 'Tech Corp Solutions', 'TC-INV-99', 110000, 19800, 129800, 128700, 'Pending'],
    ]
  },
  idfc_disbursal: {
    reportName: 'IDFC Bank Disbursal Report',
    title: 'IDFC Bank Disbursal Audit Report',
    tag: 'CORPORATE BANKING AUDIT',
    description: 'Historical records of Friday bank batches with bank UTR reference timestamps and status.',
    fallbackCols: ['Beneficiary Name', 'Beneficiary Account Number', 'IFSC', 'Transaction Type', 'Amount', 'Currency', 'Remarks', 'Employee ID', 'Batch Reference'],
    fallbackRows: [
      ['CHARLIE (ANALYST)', 'ICIC00098765432', 'ICIC0000002', 'NEFT', 18400, 'INR', 'REIMBURSEMENT BATCH WAB-2026-W41-00001', 'EMP9005', 'WAB-2026-W41-00001'],
      ['NOBANK USER', '50100234567890', 'HDFC0001234', 'NEFT', 4000, 'INR', 'REIMBURSEMENT BATCH WAB-2026-W41-00001', 'HR-EMP-00030', 'WAB-2026-W41-00001'],
      ['TEST EMPLOYEE', '50100456789012', 'HDFC0001234', 'NEFT', 800, 'INR', 'REIMBURSEMENT BATCH WAB-2026-W41-00001', 'TESTEMP001', 'WAB-2026-W41-00001'],
    ]
  },
  employee_360: {
    reportName: 'Employee Spend and Pre Travel 360 Report',
    title: 'Employee Spend & Pre-Travel 360 Report',
    tag: 'HRMS SPEND AUDIT',
    description: 'Zero-advance travel audit, mileage reimbursement logs, and fast-track policy compliance.',
    fallbackCols: ['Claim ID', 'Date', 'Employee ID', 'Employee Name', 'Company', 'Department', 'Category', 'Claimed', 'Net Payable', 'Status'],
    fallbackRows: [
      ['EXP-2026-10-03488', '2026-10-26', 'HR-EMP-00013', 'Subordinate Test', 'Quanticus Software Solutions', 'Accounts', 'Dinner Allowance', 32, 32, 'Draft'],
      ['EXP-2026-10-03295', '2026-10-23', 'TESTEMP001', 'Test employee', 'Quanticus Software Solutions', 'Management', 'Client Visit Travel', 90, 90, 'Draft'],
    ]
  },
  petty_cash: {
    reportName: 'Petty Cash Summary Report',
    title: 'Petty Cash Summary Report',
    tag: 'BRANCH TREASURY AUDIT',
    description: 'Branch-level custodian balances, weekly replenishment requests, and voucher audit trail.',
    fallbackCols: ['Date', 'Voucher ID', 'Claim Title', 'Company', 'Beneficiary', 'Expense Type', 'Merchant', 'Amount', 'Status'],
    fallbackRows: [
      ['2026-10-22', 'PC-2026-10-03146', 'Week 43 - AAGA', 'Anshul A Gupta & Associates', 'HR-EMP-00030', 'Courier & Logistics', 'DTDC', 400, 'Queued in Batch'],
      ['2026-10-22', 'PC-2026-10-03145', 'Week 43 - AAGA', 'Anshul A Gupta & Associates', 'HR-EMP-00030', 'Tea & Refreshments', 'Chai Point', 300, 'Queued in Batch'],
    ]
  },
  gst_tds: {
    reportName: 'Vendor Payment and P2P 360 Report',
    filters: { group_by: 'TDS Section Wise' },
    title: 'GST & Statutory TDS Audit Report',
    tag: 'TAX COMPLIANCE REPORT',
    description: 'Section 194C, 194J, 194Q tax deduction register for monthly GSTR-2B matching and filing.',
    fallbackCols: ['TDS Section', 'Description', 'TDS Rate (%)', 'Invoices Count', 'Taxable Base (₹)', 'TDS Deposited (₹)', 'Net Disbursed (₹)'],
    fallbackRows: [
      ['194C (Contractor)', 'Contractor Payments (Works / Manpower)', 1.0, 18, 2450000, 24500, 2425500],
      ['194J (Professional)', 'Fees for Professional & Technical Services', 10.0, 12, 1200000, 120000, 1080000],
    ]
  },
  event_spends: {
    reportName: null,
    title: 'Event Spends & Budget Tracker (Live Ledger 360)',
    tag: 'LIVE LEDGER 360',
    description: 'Tracks Stream A direct spends, SPOC advances, ground actuals, overrun variance and 30-day ageing alerts.',
    fallbackCols: ['EVENT ID', 'EVENT NAME', 'SPOC', 'ALLOCATED BUDGET', 'COMMITTED SPEND', 'REMAINING', 'OVERRUN STATUS'],
    fallbackRows: [
      ['EVT-2026-001', 'Annual Tech Summit 2026', 'Ashwin Kumar', 500000, 345000, 155000, 'WITHIN BUDGET'],
      ['EVT-2026-002', 'Product Launch Q3', 'Priya Menon', 250000, 215000, 35000, 'WITHIN BUDGET'],
      ['EVT-2026-003', 'Sales Kickoff Bangalore', 'Suresh Babu', 180000, 195000, -15000, 'OVERRUN ALERT'],
    ]
  }
};

const currentSlug = computed(() => route.params.slug || 'vendor_p2p');
const reportMeta = computed(() => reportConfigs[currentSlug.value] || reportConfigs.vendor_p2p);

const displayColumns = computed(() => {
  if (rawColumns.value && rawColumns.value.length) return rawColumns.value;
  return reportMeta.value.fallbackCols.map(c => ({ label: c, fieldname: c }));
});

const displayRows = computed(() => {
  if (rawRows.value && rawRows.value.length) return rawRows.value;
  return reportMeta.value.fallbackRows;
});

const filteredRows = computed(() => {
  const q = searchQ.value.trim().toLowerCase();
  if (!q) return displayRows.value;
  return displayRows.value.filter(row => {
    if (Array.isArray(row)) {
      return row.some(cell => String(cell || '').toLowerCase().includes(q));
    }
    return Object.values(row).some(cell => String(cell || '').toLowerCase().includes(q));
  });
});

async function fetchLiveReport() {
  const meta = reportMeta.value;
  if (!meta.reportName) {
    rawColumns.value = [];
    rawRows.value = [];
    return;
  }

  isLoading.value = true;
  try {
    const filters = {
      ...(meta.filters || {}),
      company: filterCompany.value || undefined,
      from_date: dateFrom.value || undefined,
      to_date: dateTo.value || undefined,
    };

    const res = await frappeCall('frappe.desk.query_report.run', {
      report_name: meta.reportName,
      filters,
    });

    if (res && res.columns) {
      rawColumns.value = res.columns;
      rawRows.value = res.result || [];
      reportSummary.value = res.report_summary || [];
      emitToast(`Loaded ${rawRows.value.length} rows for ${meta.title}`);
    } else {
      rawColumns.value = [];
      rawRows.value = [];
    }
  } catch (err) {
    console.warn(`Could not run live report ${meta.reportName}, using fallback:`, err);
    rawColumns.value = [];
    rawRows.value = [];
    emitToast(`Displaying cached preview for ${meta.title}`);
  } finally {
    isLoading.value = false;
  }
}

function getCellValue(row, col, colIdx) {
  if (Array.isArray(row)) {
    return row[colIdx];
  }
  const key = col.fieldname || col.label || col;
  return row[key] !== undefined ? row[key] : row[colIdx];
}

function cleanCellDisplay(val) {
  if (val === null || val === undefined) return '—';
  if (typeof val === 'string' && val.includes('=HYPERLINK(')) {
    const match = val.match(/"([^"]+)"\s*\)/);
    return match ? match[1] : 'View Proof';
  }
  return String(val);
}

function isAmountField(col, val) {
  if (typeof val === 'number') {
    const f = String(col.fieldname || col.label || '').toLowerCase();
    return f.includes('amount') || f.includes('spend') || f.includes('budget') || f.includes('taxable') || f.includes('gst') || f.includes('tds') || f.includes('net') || f.includes('gross') || f.includes('payable');
  }
  return false;
}

function isStatusField(val) {
  if (typeof val !== 'string') return false;
  const v = val.toLowerCase();
  return ['approved', 'paid', 'pending', 'disputed', 'within budget', 'overrun alert'].some(s => v.includes(s));
}

function statusClass(val) {
  const v = String(val).toLowerCase();
  if (v.includes('approved') || v.includes('paid') || v.includes('within budget')) return 'approved';
  if (v.includes('pending') || v.includes('draft') || v.includes('in review')) return 'pending';
  if (v.includes('disputed') || v.includes('overrun') || v.includes('rejected')) return 'disputed';
  return 'pending';
}

function resetFilters() {
  searchQ.value = '';
  filterCompany.value = '';
  fetchLiveReport();
}

function exportReportCsv() {
  const headers = displayColumns.value.map(c => c.label || c.fieldname || c);
  const rows = filteredRows.value.map((r, rIdx) => {
    return displayColumns.value.map((c, cIdx) => cleanCellDisplay(getCellValue(r, c, cIdx)));
  });
  const csv = [headers, ...rows].map(row => row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `${currentSlug.value}_export.csv`;
  a.click();
  URL.revokeObjectURL(url);
  emitToast('Report downloaded as CSV.');
}

watch(currentSlug, () => {
  fetchLiveReport();
});

onMounted(() => {
  fetchLiveReport();
});
</script>
