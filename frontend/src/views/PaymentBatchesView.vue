<template>
  <div>
    <section class="page-heading">
      <div>
        <span class="eyebrow">AP AUTOMATION</span>
        <h1>Payment Batches & Banking</h1>
        <p class="subtitle">Consolidated Friday disbursement batches with 15-Column IDFC Bank Excel generation and bulk UTR settlement.</p>
      </div>
      <router-link to="/payment-batches/new" class="primary-btn" style="text-decoration: none;">
        <span>＋</span> Generate Friday Batch
      </router-link>
    </section>

    <!-- Table Card -->
    <section class="table-card">
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>BATCH NUMBER</th>
              <th>BATCH TYPE</th>
              <th>CUT-OFF DATE</th>
              <th>TOTAL CLAIMS</th>
              <th>TOTAL PAYABLE</th>
              <th>STATUS</th>
              <th>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in batches" :key="item.id">
              <td>
                <router-link :to="`/payment-batches/${item.id}`" style="color: var(--purple-dark); font-weight: 700; text-decoration: none;">
                  {{ item.id }}
                </router-link>
              </td>
              <td>{{ item.type }}</td>
              <td>{{ item.date }}</td>
              <td>{{ item.claims }} Claims</td>
              <td class="amount">{{ formatMoney(item.amount) }}</td>
              <td><span class="status" :class="item.status === 'Disbursed' ? 'approved' : 'pending'">{{ item.status }}</span></td>
              <td>
                <div class="actions">
                  <router-link :to="`/payment-batches/${item.id}`" class="action-btn" title="View Batch & Payout Grid" style="text-decoration: none;">⌕</router-link>
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
import { ref } from 'vue';
import { formatMoney } from '../utils/api';

const emit = defineEmits(['toast']);
function emitToast(msg) { emit('toast', msg); }

const batches = ref([
  { id: 'PB-2026-10-W4', type: 'Friday Vendor Accounts Batch', date: '24-10-2026', claims: 14, amount: 685000, status: 'Disbursed' },
  { id: 'PB-2026-10-W3', type: 'Friday Vendor Accounts Batch', date: '17-10-2026', claims: 11, amount: 520000, status: 'Disbursed' },
  { id: 'PB-2026-10-W5', type: 'Friday Vendor Accounts Batch (Upcoming)', date: '31-10-2026', claims: 8, amount: 472500, status: 'Ready for Review' },
]);
</script>

