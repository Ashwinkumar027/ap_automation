<template>
  <div>
    <section class="page-heading">
      <div>
        <span class="eyebrow">AP AUTOMATION</span>
        <h1>Purchase Orders & GRN</h1>
        <p class="subtitle">Purchase Order management with 3-Way Match validation and Goods Receipt Note (GRN) fulfillment.</p>
      </div>
      <router-link to="/purchase-orders/new" class="primary-btn" style="text-decoration: none;">
        <span>＋</span> New Purchase Order
      </router-link>
    </section>

    <!-- Table Card -->
    <section class="table-card">
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>PO NUMBER</th>
              <th>VENDOR</th>
              <th>ORDER DATE</th>
              <th>AMOUNT</th>
              <th>GRN MATCH</th>
              <th>STATUS</th>
              <th>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in pos" :key="item.po">
              <td>
                <router-link :to="`/purchase-orders/${item.po}`" style="color: var(--purple-dark); font-weight: 700; text-decoration: none;">
                  {{ item.po }}
                </router-link>
              </td>
              <td><strong>{{ item.vendor }}</strong></td>
              <td>{{ item.date }}</td>
              <td class="amount">{{ formatMoney(item.amount) }}</td>
              <td>
                <div class="progress-label">{{ item.grn }}% Received</div>
                <div class="progress approved">
                  <span :style="{ width: `${item.grn}%` }"></span>
                </div>
              </td>
              <td><span class="status approved">{{ item.status }}</span></td>
              <td>
                <div class="actions">
                  <router-link :to="`/purchase-orders/${item.po}`" class="action-btn" title="View details" style="text-decoration: none;">⌕</router-link>
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
import { ref, onMounted } from 'vue';
import { formatMoney, frappeGetDocList, formatDate } from '../utils/api';

const emit = defineEmits(['toast']);
function emitToast(msg) { emit('toast', msg); }

const pos = ref([
  { po: 'PO-2026-001', vendor: 'Grand Convention Center & Resort', date: '20-10-2026', amount: 245000, grn: 100, status: 'Completed' },
  { po: 'PO-2026-002', vendor: 'Tech Corp Solutions India Pvt Ltd', date: '18-10-2026', amount: 130000, grn: 100, status: 'Approved / Issued' },
  { po: 'PO-2026-003', vendor: 'Event Craft Media', date: '15-10-2026', amount: 85000, grn: 80, status: 'Approved / Issued' },
  { po: 'PO-2026-004', vendor: 'Office Supplies Co.', date: '12-10-2026', amount: 22500, grn: 100, status: 'Completed' },
]);

onMounted(async () => {
  try {
    const list = await frappeGetDocList('AP Purchase Order', {
      fields: ['name', 'vendor', 'po_date', 'total_amount', 'status'],
      limit: 20,
    });
    if (list && list.length) {
      pos.value = list.map(r => ({
        po: r.name,
        vendor: r.vendor || 'Vendor',
        date: formatDate(r.po_date),
        amount: Number(r.total_amount || 0),
        grn: 100,
        status: r.status || 'Approved / Issued',
      }));
    }
  } catch (err) {
    console.warn('Fallback to demo POs:', err);
  }
});
</script>

