<template>
  <div>
    <section class="page-heading">
      <div>
        <span class="eyebrow">AP AUTOMATION</span>
        <h1>Employee Claims</h1>
        <p class="subtitle">Review and track staff reimbursement claims. Zero-advance direct spend policy enforced.</p>
      </div>
      <router-link to="/employee-claims/new" class="primary-btn" style="text-decoration: none;">
        <span>＋</span> New Employee Claim
      </router-link>
    </section>

    <!-- KPI Ribbon -->
    <section class="kpis">
      <KpiCard icon="♙" color="purple" :value="claims.length" label="Total Claims" trend="↗ +8% this month" spark-color="#7655ff" />
      <KpiCard icon="◷" color="amber" :value="pendingCount" label="Pending Audit" trend="↗ +3% this month" spark-color="#f0a000" />
      <KpiCard icon="✓" color="green" :value="approvedCount" label="Approved / Settled" trend="↗ +14% this month" spark-color="#05bd88" />
      <KpiCard icon="!" color="red" :value="disputedCount" label="Policy Exceptions" trend="↓ -2% this month" trend-color="#e43f50" spark-color="#ff6676" />
    </section>

    <!-- Table Card -->
    <section class="table-card">
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>CLAIM ID</th>
              <th>EMPLOYEE</th>
              <th>EXPENSE TYPE</th>
              <th>CLAIM DATE</th>
              <th>AMOUNT</th>
              <th>STATUS</th>
              <th>POLICY AUDIT</th>
              <th>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in claims" :key="item.id">
              <td>
                <router-link :to="`/employee-claims/${item.id}`" style="color: var(--purple-dark); font-weight: 700; text-decoration: none;">
                  {{ item.id }}
                </router-link>
              </td>
              <td>
                <div class="vendor-cell">
                  <div class="vendor-logo">{{ getInitials(item.employee) }}</div>
                  <div>
                    <div class="vendor-name">{{ item.employee }}</div>
                    <div class="vendor-type">{{ item.department }}</div>
                  </div>
                </div>
              </td>
              <td>{{ item.category }}</td>
              <td>{{ item.date }}</td>
              <td class="amount">{{ formatMoney(item.amount) }}</td>
              <td><span class="status" :class="item.status.toLowerCase().replace(/\s+/g, '-')">{{ item.status }}</span></td>
              <td>
                <span style="font-size: 10px; font-weight: 700; color: #08a96a;">✓ Fast-Track Approved</span>
              </td>
              <td>
                <div class="actions">
                  <router-link :to="`/employee-claims/${item.id}`" class="action-btn" title="View details" style="text-decoration: none;">⌕</router-link>
                  <router-link :to="`/employee-claims/${item.id}`" class="action-btn" title="Audit" style="text-decoration: none;">✎</router-link>
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

const claims = ref([
  { id: 'EC-2026-0045', employee: 'Ramesh Kumar', department: 'Engineering', category: 'Flight Ticket (Chennai - Bangalore)', date: '24-10-2026', amount: 4200, status: 'Approved' },
  { id: 'EC-2026-0046', employee: 'Ramesh Kumar', department: 'Engineering', category: 'Local Taxi Travel', date: '24-10-2026', amount: 1200, status: 'Pending' },
  { id: 'EC-2026-0047', employee: 'Priya Nair', department: 'HR', category: 'Client Team Dinner', date: '23-10-2026', amount: 3850, status: 'Approved' },
  { id: 'EC-2026-0048', employee: 'Arun S', department: 'Operations', category: 'Mobile & Internet Reimbursement', date: '22-10-2026', amount: 1500, status: 'Approved' },
  { id: 'EC-2026-0049', employee: 'Suresh Babu', department: 'Finance', category: 'Hotel Stay (Mumbai)', date: '21-10-2026', amount: 8900, status: 'Pending' },
]);

onMounted(async () => {
  try {
    const list = await frappeGetDocList('Employee Reimbursement Claim', {
      fields: ['name', 'employee_name', 'department', 'claim_category', 'posting_date', 'total_claim_amount', 'net_payable_amount', 'status'],
      limit: 50,
      order_by: 'creation desc',
    });
    if (list && list.length) {
      claims.value = list.map(r => ({
        id: r.name,
        employee: r.employee_name || 'Employee',
        department: r.department || 'Operations',
        category: r.claim_category || 'Travel & Per Diem',
        date: formatDate(r.posting_date),
        amount: Number(r.net_payable_amount || r.total_claim_amount || 0),
        status: r.status || 'Pending',
      }));
    }
  } catch (err) {
    console.warn('Fallback to demo employee claims:', err);
  }
});

const pendingCount = computed(() => claims.value.filter(x => x.status === 'Pending' || x.status === 'Draft').length);
const approvedCount = computed(() => claims.value.filter(x => x.status === 'Approved' || x.status === 'Paid').length);
const disputedCount = computed(() => claims.value.filter(x => x.status === 'Disputed' || x.status === 'Returned to Employee').length);
</script>
