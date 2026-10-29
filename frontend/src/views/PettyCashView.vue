<template>
  <div>
    <!-- Page Heading -->
    <section class="page-heading">
      <div>
        <span class="eyebrow">AP AUTOMATION</span>
        <h1>Petty Cash (Lane 1)</h1>
        <p class="subtitle">Branch imprest management, weekly custodian replenishment, and statutory voucher audits.</p>
      </div>
      <router-link to="/petty-cash/new" class="primary-btn" style="text-decoration: none;">
        <span>＋</span> New Petty Cash Voucher
      </router-link>
    </section>

    <!-- KPI Cards -->
    <section class="kpis" aria-label="Petty Cash Summary">
      <KpiCard
        icon="💵"
        color="purple"
        :value="vouchers.length"
        label="Total Vouchers"
        trend="↗ Imprest Active"
        spark-color="#7655ff"
        spark-path="M1 23 C10 23 10 12 18 16 S30 22 39 10 S53 18 61 8 S73 5 79 2"
      />
      <KpiCard
        icon="◷"
        color="amber"
        :value="pendingCount"
        label="Pending Approvals"
        trend="Weekly Tuesday Cutoff"
        spark-color="#f0a000"
        spark-path="M1 25 C10 21 14 25 21 17 S31 24 39 14 S52 18 59 7 S71 11 79 2"
      />
      <KpiCard
        icon="✓"
        color="green"
        :value="auditedCount"
        label="Accounts Audited"
        trend="Ready for Replenish"
        spark-color="#05bd88"
        spark-path="M1 23 C10 20 13 24 20 15 S31 21 40 12 S50 20 59 7 S71 10 79 2"
      />
      <KpiCard
        icon="!"
        color="red"
        :value="disbursedCount"
        label="Disbursed (Settled)"
        trend="Imprest Restored"
        spark-color="#ff6676"
        spark-path="M1 23 C10 23 10 12 18 16 S30 22 39 10 S53 18 61 8 S73 5 79 2"
      />
    </section>

    <!-- Table Card -->
    <section class="table-card">
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>VOUCHER ID</th>
              <th>CUSTODIAN / BRANCH</th>
              <th>COMPANY</th>
              <th>POSTING DATE</th>
              <th>AMOUNT</th>
              <th>BILLS ATTACHED</th>
              <th>STATUS</th>
              <th>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in vouchers" :key="item.id">
              <td>
                <router-link :to="`/petty-cash/${item.id}`" style="color: var(--purple-dark); font-weight: 700; text-decoration: none;">
                  {{ item.id }}
                </router-link>
              </td>
              <td>
                <div class="vendor-cell">
                  <div class="vendor-logo">{{ getInitials(item.custodian) }}</div>
                  <div>
                    <div class="vendor-name">{{ item.custodian }}</div>
                    <div class="vendor-type">{{ item.branch || 'Branch Custodian' }}</div>
                  </div>
                </div>
              </td>
              <td>{{ item.company }}</td>
              <td>{{ item.date }}</td>
              <td class="amount">{{ formatMoney(item.amount) }}</td>
              <td><span style="font-weight: 700;">{{ item.billsCount }} Bills</span></td>
              <td>
                <span class="status" :class="statusClass(item.status)">{{ item.status }}</span>
              </td>
              <td>
                <div class="actions">
                  <router-link :to="`/petty-cash/${item.id}`" class="action-btn" title="View details" style="text-decoration: none;">⌕</router-link>
                  <router-link :to="`/petty-cash/${item.id}`" class="action-btn" title="Audit" style="text-decoration: none;">✎</router-link>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import KpiCard from '../components/KpiCard.vue';
import { formatMoney, initials as getInitials, frappeGetDocList, formatDate } from '../utils/api';

const emit = defineEmits(['toast']);
function emitToast(msg) { emit('toast', msg); }

const vouchers = ref([
  { id: 'PC-2026-W43-AAG', custodian: 'Receptionist / Front Desk', branch: 'Chennai HQ', company: 'Anshul A Gupta & Associates', date: '26-10-2026', amount: 8450, billsCount: 6, status: 'Accounts Audited' },
  { id: 'PC-2026-W43-QSS', custodian: 'Office Admin', branch: 'Bangalore Tech Park', company: 'Quanticus Software Solutions', date: '25-10-2026', amount: 12400, billsCount: 9, status: 'Pending Admin Approval' },
  { id: 'PC-2026-W42-AAG', custodian: 'Receptionist / Front Desk', branch: 'Chennai HQ', company: 'Anshul A Gupta & Associates', date: '19-10-2026', amount: 7200, billsCount: 5, status: 'Disbursed' },
  { id: 'PC-2026-W42-QSS', custodian: 'Office Admin', branch: 'Bangalore Tech Park', company: 'Quanticus Software Solutions', date: '18-10-2026', amount: 9800, billsCount: 8, status: 'Disbursed' },
]);

onMounted(async () => {
  try {
    const list = await frappeGetDocList('Petty Cash Entry', {
      fields: ['name', 'custodian', 'company', 'posting_date', 'total_amount', 'status'],
      limit: 25,
    });
    if (list && list.length) {
      vouchers.value = list.map(r => ({
        id: r.name,
        custodian: r.custodian || 'Custodian',
        branch: 'Branch Office',
        company: r.company || 'Company',
        date: formatDate(r.posting_date),
        amount: Number(r.total_amount || 0),
        billsCount: 5,
        status: r.status === 'Disbursed' ? 'Disbursed' : r.status === 'Accounts Audited' ? 'Accounts Audited' : 'Pending Admin Approval',
      }));
    }
  } catch (err) {
    console.warn('Fallback to demo petty cash vouchers:', err);
  }
});

const pendingCount = computed(() => vouchers.value.filter(x => x.status.includes('Pending')).length);
const auditedCount = computed(() => vouchers.value.filter(x => x.status === 'Accounts Audited').length);
const disbursedCount = computed(() => vouchers.value.filter(x => x.status === 'Disbursed').length);

function statusClass(s) {
  if (s === 'Disbursed') return 'approved';
  if (s === 'Accounts Audited') return 'paid';
  if (s.includes('Pending')) return 'pending';
  return 'pending';
}
</script>

