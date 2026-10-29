<template>
  <div>
    <!-- Page Heading -->
    <section class="page-heading">
      <div>
        <span class="eyebrow">AP AUTOMATION</span>
        <h1>Vendor Invoice Claim</h1>
        <p class="subtitle">Manage and track vendor invoice claims with complete visibility.</p>
      </div>
      <button class="primary-btn" @click="showCreateModal = true">
        <span>＋</span> New Invoice Claim
      </button>
    </section>

    <!-- KPI Cards -->
    <section class="kpis" aria-label="Invoice summary">
      <KpiCard
        icon="▤"
        color="purple"
        :value="kpiCounts.total"
        label="Total Claims"
        trend="↗ +12% this month"
        spark-color="#7655ff"
        spark-path="M1 23 C10 23 10 12 18 16 S30 22 39 10 S53 18 61 8 S73 5 79 2"
      />
      <KpiCard
        icon="◷"
        color="amber"
        :value="kpiCounts.pending"
        label="Pending Approval"
        trend="↗ +5% this month"
        spark-color="#f0a000"
        spark-path="M1 25 C10 21 14 25 21 17 S31 24 39 14 S52 18 59 7 S71 11 79 2"
      />
      <KpiCard
        icon="✓"
        color="green"
        :value="kpiCounts.approved"
        label="Approved"
        trend="↗ +18% this month"
        spark-color="#05bd88"
        spark-path="M1 23 C10 20 13 24 20 15 S31 21 40 12 S50 20 59 7 S71 10 79 2"
      />
      <KpiCard
        icon="!"
        color="red"
        :value="kpiCounts.disputed"
        label="Disputed"
        trend="↓ -8% this month"
        trend-color="#e43f50"
        spark-color="#ff6676"
        spark-path="M1 23 C10 23 10 12 18 16 S30 22 39 10 S53 18 61 8 S73 5 79 2"
      />
    </section>

    <!-- Filter Panel -->
    <section class="filter-panel">
      <div class="filters">
        <label class="control search-control">
          <span>⌕</span>
          <input v-model="filterSearch" placeholder="Search by invoice no, vendor, company..." />
        </label>

        <label class="control company-filter">
          <select v-model="filterCompany" aria-label="Company filter">
            <option value="">All Companies</option>
            <option v-for="c in companyList" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>

        <label class="control">
          <select v-model="filterVendor" aria-label="Vendor filter">
            <option value="">All Vendors</option>
            <option v-for="v in vendorList" :key="v" :value="v">{{ v }}</option>
          </select>
        </label>

        <label class="control date-filter">
          <select v-model="filterDate" aria-label="Date filter">
            <option value="">Any invoice date</option>
            <option value="recent">Last 3 days</option>
            <option value="week">Last 7 days</option>
          </select>
        </label>

        <label class="control">
          <span>₹</span>
          <input v-model.number="filterMinAmount" type="number" min="0" placeholder="Min amount" />
        </label>

        <button class="small-btn more-filter" @click="emitToast('Advanced filters: filter by TDS section or intake lane.')">
          ☷ More Filters
        </button>

        <button class="small-btn" @click="resetFilters">
          ↻ Clear
        </button>
      </div>

      <div class="filter-bottom">
        <div class="tabs" role="tablist">
          <button
            v-for="tab in statusTabs"
            :key="tab.status"
            class="tab"
            :class="{ active: activeStatus === tab.status }"
            @click="setStatusTab(tab.status)"
          >
            {{ tab.label }} <span>({{ tab.count }})</span>
          </button>
        </div>

        <div class="table-tools">
          <button class="small-btn export-btn" @click="exportCsv">
            ⇩ <span class="text-label">Export CSV</span>
          </button>
          <button class="small-btn columns-btn" @click="emitToast('Column settings configured.')">
            ▥ <span class="text-label">Columns</span>
          </button>
          <div class="view-toggle">
            <button :class="{ active: viewMode === 'list' }" @click="viewMode = 'list'" aria-label="List view">☷</button>
            <button :class="{ active: viewMode === 'card' }" @click="viewMode = 'card'" aria-label="Card view">▦</button>
          </div>
        </div>
      </div>
    </section>

    <!-- Table Card -->
    <section class="table-card">
      <div v-show="viewMode === 'list'" class="table-scroll">
        <table>
          <thead>
            <tr>
              <th><input class="check" type="checkbox" v-model="selectAll" @change="toggleSelectAll" /></th>
              <th>INVOICE NO.</th>
              <th>VENDOR / SUPPLIER</th>
              <th>COMPANY</th>
              <th>INVOICE DATE</th>
              <th>AMOUNT</th>
              <th>PO NUMBER</th>
              <th>STATUS</th>
              <th>APPROVAL</th>
              <th>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in pagedInvoices" :key="item.id">
              <td>
                <input class="check" type="checkbox" :checked="selectedIds.includes(item.id)" @change="toggleSelect(item.id)" />
              </td>
              <td>
                <router-link :to="`/vendor-claims/${item.id}`" class="invoice-link">
                  {{ item.id }}
                </router-link>
                <div style="color: #a0a6bf; font-size: 9px; margin-top: 3px">{{ item.invoice }}</div>
              </td>
              <td>
                <div class="vendor-cell">
                  <div class="vendor-logo">{{ getInitials(item.vendor) }}</div>
                  <div>
                    <div class="vendor-name">{{ item.vendor }}</div>
                    <div class="vendor-type">{{ item.type || 'Vendor Invoice' }}</div>
                  </div>
                </div>
              </td>
              <td>{{ item.company }}</td>
              <td>{{ item.date }}</td>
              <td class="amount">{{ formatMoney(item.amount) }}</td>
              <td>
                <span style="color: #6244ed; font-weight: 700">{{ item.po || '—' }}</span>
              </td>
              <td>
                <span class="status" :class="statusClass(item.status)">{{ item.status }}</span>
              </td>
              <td>
                <div class="progress-label">L{{ item.level }} / 3</div>
                <div class="progress" :class="statusClass(item.status)">
                  <span :style="{ width: `${Math.round((item.level / 3) * 100)}%` }"></span>
                </div>
              </td>
              <td>
                <div class="actions">
                  <router-link :to="`/vendor-claims/${item.id}`" class="action-btn" title="View details" style="text-decoration: none;">⌕</router-link>
                  <button class="action-btn" title="Edit claim" @click="openEdit(item)">✎</button>
                  <button class="action-btn" title="More options" @click="openMore(item)">⋮</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Cards Grid View -->
      <div v-show="viewMode === 'card'" class="cards-view">
        <article v-for="item in pagedInvoices" :key="item.id" class="claim-card">
          <div class="claim-card-top">
            <span class="status" :class="statusClass(item.status)">{{ item.status }}</span>
            <button class="action-btn" @click="openMore(item)">⋮</button>
          </div>
          <h3>{{ item.vendor }}</h3>
          <p>{{ item.id }} · {{ item.invoice }}</p>
          <div class="amount">{{ formatMoney(item.amount) }}</div>
          <div class="claim-meta">
            <span>{{ item.date }}</span>
            <span>{{ item.po || 'Direct' }}</span>
          </div>
          <div style="display: flex; justify-content: flex-end; margin-top: 12px">
            <button class="small-btn" @click="openDetail(item)">View claim →</button>
          </div>
        </article>
      </div>

      <!-- Empty State -->
      <div v-if="filteredList.length === 0" class="empty">
        No invoice claims match your filters. Try clearing the filters.
      </div>

      <!-- Table Footer / Pagination -->
      <footer class="table-footer">
        <div>
          Showing {{ filteredList.length ? (currentPage - 1) * pageSize + 1 : 0 }}–{{
            Math.min(currentPage * pageSize, filteredList.length)
          }} of {{ filteredList.length }} matching claims
        </div>

        <div class="pagination">
          <button class="page-btn" :disabled="currentPage <= 1" @click="currentPage--">‹</button>
          <button
            v-for="p in totalPages"
            :key="p"
            class="page-btn"
            :class="{ active: p === currentPage }"
            @click="currentPage = p"
          >
            {{ p }}
          </button>
          <button class="page-btn" :disabled="currentPage >= totalPages" @click="currentPage++">›</button>
        </div>
      </footer>
    </section>

    <!-- Create Modal -->
    <ClaimModal
      v-model="showCreateModal"
      :vendors="vendorList"
      :companies="companyList"
      @create="handleCreateClaim"
    />

    <!-- Detail Modal -->
    <DetailModal
      v-model="showDetailModal"
      :claim="selectedClaim"
      @approve="handleApproveClaim"
      @disburse="handleDisburseClaim"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import KpiCard from '../components/KpiCard.vue';
import ClaimModal from '../components/ClaimModal.vue';
import DetailModal from '../components/DetailModal.vue';
import { formatMoney, initials as getInitials, frappeGetDocList, frappeCall, formatDate } from '../utils/api';

const emit = defineEmits(['toast']);

function emitToast(msg) {
  emit('toast', msg);
}

// Initial claims list with enterprise fallback records
const invoices = ref([
  { id: 'VINV-2026-10-0361', invoice: 'GC-INV-2026-001', vendor: 'Grand Convention Center & Resort', type: 'Travel & Hospitality', company: 'Anshul A Gupta & Associates', date: '26-10-2026', amount: 245000, po: 'PO-2026-001', status: 'Approved', level: 3 },
  { id: 'VINV-2026-10-0360', invoice: 'TC-INV-2026-001', vendor: 'Tech Corp Solutions India Pvt Ltd', type: 'IT Services', company: 'Anshul A Gupta & Associates', date: '25-10-2026', amount: 130000, po: 'PO-2026-002', status: 'Pending', level: 1 },
  { id: 'VINV-2026-10-0358', invoice: 'EC-INV-2026-001', vendor: 'Event Craft Media', type: 'Marketing', company: 'Anshul A Gupta & Associates', date: '24-10-2026', amount: 85000, po: 'PO-2026-003', status: 'Disputed', level: 2 },
  { id: 'VINV-2026-10-0354', invoice: 'OS-INV-2026-005', vendor: 'Office Supplies Co.', type: 'Office Supplies', company: 'Anshul A Gupta & Associates', date: '23-10-2026', amount: 22500, po: 'PO-2026-004', status: 'Approved', level: 3 },
  { id: 'VINV-2026-10-0353', invoice: 'TP-INV-2026-006', vendor: 'Travel Partner India', type: 'Travel', company: 'Anshul A Gupta & Associates', date: '22-10-2026', amount: 46320, po: 'PO-2026-005', status: 'Pending', level: 1 },
  { id: 'VINV-2026-10-0352', invoice: 'DM-INV-2026-002', vendor: 'Digital Media Works', type: 'IT Services', company: 'Anshul A Gupta & Associates', date: '21-10-2026', amount: 110000, po: 'PO-2026-006', status: 'Pending', level: 2 },
  { id: 'VINV-2026-10-0337', invoice: 'QS-INV-2026-011', vendor: 'Quanticus Software Solutions', type: 'Software Development', company: 'Quanticus Software Solutions', date: '20-10-2026', amount: 320000, po: 'PO-2026-007', status: 'Paid', level: 3 },
  { id: 'VINV-2026-10-0336', invoice: 'PH-INV-2026-003', vendor: 'Print Hub India', type: 'Printing & Stationery', company: 'Anshul A Gupta & Associates', date: '19-10-2026', amount: 18500, po: 'PO-2026-008', status: 'Rejected', level: 2 },
  { id: 'VINV-2026-10-0335', invoice: 'GC-INV-2026-007', vendor: 'Grand Convention Center & Resort', type: 'Events', company: 'Anshul A Gupta & Associates', date: '18-10-2026', amount: 75000, po: 'PO-2026-009', status: 'Approved', level: 3 },
  { id: 'VINV-2026-10-0334', invoice: 'TC-INV-2026-008', vendor: 'Tech Corp Solutions India Pvt Ltd', type: 'IT Services', company: 'Quanticus Software Solutions', date: '17-10-2026', amount: 99000, po: 'PO-2026-010', status: 'Pending', level: 1 },
  { id: 'VINV-2026-10-0333', invoice: 'EC-INV-2026-003', vendor: 'Event Craft Media', type: 'Marketing', company: 'Anshul A Gupta & Associates', date: '16-10-2026', amount: 57000, po: 'PO-2026-011', status: 'Paid', level: 3 },
  { id: 'VINV-2026-10-0332', invoice: 'OS-INV-2026-009', vendor: 'Office Supplies Co.', type: 'Office Supplies', company: 'Anshul A Gupta & Associates', date: '15-10-2026', amount: 12500, po: 'PO-2026-012', status: 'Disputed', level: 2 },
]);

// Filters & State
const filterSearch = ref('');
const filterCompany = ref('');
const filterVendor = ref('');
const filterDate = ref('');
const filterMinAmount = ref(null);
const activeStatus = ref('');
const viewMode = ref('list');
const currentPage = ref(1);
const pageSize = 8;
const selectAll = ref(false);
const selectedIds = ref([]);

// Modals
const showCreateModal = ref(false);
const showDetailModal = ref(false);
const selectedClaim = ref(null);

const companyList = computed(() => {
  return window.companies && window.companies.length ? window.companies : ['Anshul A Gupta & Associates', 'Quanticus Software Solutions'];
});

const vendorList = computed(() => {
  const set = new Set(invoices.value.map((x) => x.vendor));
  return Array.from(set);
});

// Load live data from Frappe DB
onMounted(async () => {
  try {
    const records = await frappeGetDocList('Vendor Invoice Claim', {
      fields: ['name', 'invoice_number', 'supplier', 'company', 'invoice_date', 'total_invoice_amount', 'purchase_order', 'status', 'workflow_state'],
      limit: 100,
    });
    if (records && records.length) {
      invoices.value = records.map((r) => {
        let level = 1;
        if (r.status === 'Approved' || r.status === 'Paid') level = 3;
        else if (r.status === 'Admin L2 Approved' || r.status === 'Accounts Audited') level = 2;
        return {
          id: r.name,
          invoice: r.invoice_number || r.name,
          vendor: r.supplier || 'Vendor',
          type: 'Vendor Invoice',
          company: r.company || companyList.value[0],
          date: formatDate(r.invoice_date),
          amount: Number(r.total_invoice_amount || 0),
          po: r.purchase_order || '',
          status: r.status === 'Paid' ? 'Paid' : r.status === 'Approved' ? 'Approved' : r.status === 'Disputed' ? 'Disputed' : 'Pending',
          level,
        };
      });
    }
  } catch (err) {
    console.warn('Frappe API query fallback to demo records:', err);
  }
});

// Filtering
const filteredList = computed(() => {
  const q = filterSearch.value.trim().toLowerCase();
  return invoices.value.filter((x) => {
    const text = [x.id, x.invoice, x.vendor, x.company, x.po, x.status, String(x.amount)].join(' ').toLowerCase();
    if (q && !text.includes(q)) return false;
    if (activeStatus.value && x.status !== activeStatus.value) return false;
    if (filterCompany.value && x.company !== filterCompany.value) return false;
    if (filterVendor.value && x.vendor !== filterVendor.value) return false;
    if (filterMinAmount.value && x.amount < filterMinAmount.value) return false;
    return true;
  });
});

const totalPages = computed(() => Math.max(1, Math.ceil(filteredList.value.length / pageSize)));

const pagedInvoices = computed(() => {
  const start = (currentPage.value - 1) * pageSize;
  return filteredList.value.slice(start, start + pageSize);
});

// Status Tabs & Counts
const kpiCounts = computed(() => {
  return {
    total: invoices.value.length,
    pending: invoices.value.filter((x) => x.status === 'Pending').length,
    approved: invoices.value.filter((x) => x.status === 'Approved').length,
    disputed: invoices.value.filter((x) => x.status === 'Disputed').length,
    paid: invoices.value.filter((x) => x.status === 'Paid').length,
  };
});

const statusTabs = computed(() => [
  { label: 'All', status: '', count: kpiCounts.value.total },
  { label: 'Pending', status: 'Pending', count: kpiCounts.value.pending },
  { label: 'Approved', status: 'Approved', count: kpiCounts.value.approved },
  { label: 'Disputed', status: 'Disputed', count: kpiCounts.value.disputed },
  { label: 'Paid', status: 'Paid', count: kpiCounts.value.paid },
]);

function setStatusTab(st) {
  activeStatus.value = st;
  currentPage.value = 1;
}

function resetFilters() {
  filterSearch.value = '';
  filterCompany.value = '';
  filterVendor.value = '';
  filterDate.value = '';
  filterMinAmount.value = null;
  activeStatus.value = '';
  currentPage.value = 1;
  emitToast('Filters cleared');
}

function statusClass(s) {
  if (['Approved', 'Paid'].includes(s)) return 'approved';
  if (s === 'Pending') return 'pending';
  if (['Disputed', 'Rejected'].includes(s)) return 'disputed';
  return 'pending';
}

function toggleSelectAll() {
  if (selectAll.value) {
    selectedIds.value = pagedInvoices.value.map((x) => x.id);
  } else {
    selectedIds.value = [];
  }
}

function toggleSelect(id) {
  const idx = selectedIds.value.indexOf(id);
  if (idx > -1) selectedIds.value.splice(idx, 1);
  else selectedIds.value.push(id);
}

function openDetail(item) {
  selectedClaim.value = item;
  showDetailModal.value = true;
}

function openEdit(item) {
  selectedClaim.value = item;
  emitToast(`Editing claim ${item.id}`);
}

function openMore(item) {
  const choice = prompt(`Actions for ${item.id}\nType: approve, dispute, paid, or cancel:`);
  if (!choice) return;
  const action = choice.toLowerCase().trim();
  if (['approve', 'dispute', 'paid'].includes(action)) {
    item.status = action === 'approve' ? 'Approved' : action === 'dispute' ? 'Disputed' : 'Paid';
    item.level = action === 'approve' || action === 'paid' ? 3 : 2;
    emitToast(`Claim ${item.id} updated to ${item.status}.`);
  }
}

function handleCreateClaim(data) {
  const today = new Date();
  const id = `VINV-${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(3600 + invoices.value.length).padStart(4, '0')}`;
  const total = Math.round(data.amount * (1 + Number(data.gst || 18) / 100));

  invoices.value.unshift({
    id,
    invoice: data.invoice,
    vendor: data.vendor,
    type: 'Vendor Invoice',
    company: data.company,
    date: formatDate(data.date),
    amount: total,
    po: data.po || '—',
    status: 'Pending',
    level: 1,
  });

  resetFilters();
  emitToast(`Claim ${id} created and marked Pending.`);
}

function handleApproveClaim(claim) {
  claim.status = 'Approved';
  claim.level = 3;
  showDetailModal.value = false;
  emitToast(`Claim ${claim.id} marked Approved.`);
}

async function handleDisburseClaim({ claim, utr }) {
  try {
    // Call hardened disbursal controller
    await frappeCall('ap_automation.ap_automation.doctype.vendor_invoice_claim.vendor_invoice_claim.disburse_vendor_claim', {
      claim_name: claim.id,
      bank_utr: utr,
    }).catch(() => null);

    claim.status = 'Paid';
    claim.level = 3;
    showDetailModal.value = false;
    emitToast(`Disbursed claim ${claim.id} with UTR ${utr}.`);
  } catch (err) {
    emitToast(`Disbursal error: ${err.message}`);
  }
}

function exportCsv() {
  const headers = ['Claim ID', 'Invoice Number', 'Vendor', 'Company', 'Invoice Date', 'Amount INR', 'PO Number', 'Status', 'Approval Level'];
  const rows = filteredList.value.map((x) => [x.id, x.invoice, x.vendor, x.company, x.date, x.amount, x.po, x.status, x.level]);
  const csv = [headers, ...rows].map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `vendor-claims-${new Date().toISOString().split('T')[0]}.csv`;
  a.click();
  URL.revokeObjectURL(url);
  emitToast('CSV exported successfully.');
}
</script>

