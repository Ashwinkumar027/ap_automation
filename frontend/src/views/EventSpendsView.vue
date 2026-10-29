<template>
  <div>
    <section class="page-heading">
      <div>
        <span class="eyebrow">AP AUTOMATION</span>
        <h1>Event Spends & Advances</h1>
        <p class="subtitle">Live multi-stream event budget tracking (Stream A Vendor Direct + Stream B SPOC Imprest).</p>
      </div>
      <router-link to="/event-spends/new" class="primary-btn" style="text-decoration: none;">
        <span>＋</span> New Event Master
      </router-link>
    </section>

    <!-- KPI Ribbon -->
    <section class="kpis">
      <KpiCard icon="◉" color="purple" :value="events.length" label="Active Events" trend="↗ Active" spark-color="#7655ff" />
      <KpiCard icon="◷" color="amber" :value="formatMoney(totalAllocated)" label="Total Budget" trend="Committed" spark-color="#f0a000" />
      <KpiCard icon="✓" color="green" :value="formatMoney(totalCommitted)" label="Committed Spend" trend="Stream A + B" spark-color="#05bd88" />
      <KpiCard icon="!" color="red" :value="overrunCount" label="Overrun Warnings" trend=">80% Utilized" trend-color="#e43f50" spark-color="#ff6676" />
    </section>

    <!-- Table Card -->
    <section class="table-card">
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>EVENT CODE</th>
              <th>EVENT NAME</th>
              <th>SPOC</th>
              <th>ALLOCATED BUDGET</th>
              <th>COMMITTED SPEND</th>
              <th>REMAINING</th>
              <th>UTILIZATION</th>
              <th>STATUS</th>
              <th>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in events" :key="item.id">
              <td>
                <router-link :to="`/event-spends/${item.id}`" style="color: var(--purple-dark); font-weight: 700; text-decoration: none;">
                  {{ item.id }}
                </router-link>
              </td>
              <td><strong>{{ item.name }}</strong></td>
              <td>{{ item.spoc }}</td>
              <td class="amount">{{ formatMoney(item.budget) }}</td>
              <td class="amount">{{ formatMoney(item.committed) }}</td>
              <td class="amount">{{ formatMoney(item.remaining) }}</td>
              <td>
                <div class="progress-label">{{ item.utilPct }}%</div>
                <div class="progress" :class="{ disputed: item.utilPct > 80 }">
                  <span :style="{ width: `${Math.min(item.utilPct, 100)}%` }"></span>
                </div>
              </td>
              <td>
                <span class="status" :class="item.utilPct > 100 ? 'disputed' : item.utilPct > 80 ? 'pending' : 'approved'">
                  {{ item.utilPct > 100 ? 'OVERRUN ALERT' : item.utilPct > 80 ? 'APPROACHING LIMIT' : 'WITHIN BUDGET' }}
                </span>
              </td>
              <td>
                <div class="actions">
                  <router-link :to="`/event-spends/${item.id}`" class="action-btn" title="Settlement Delta Math" style="text-decoration: none;">⌕</router-link>
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
import { formatMoney, frappeGetDocList } from '../utils/api';

const emit = defineEmits(['toast']);
function emitToast(msg) { emit('toast', msg); }

const events = ref([
  { id: 'EVT-2026-001', name: 'Annual Tech Summit 2026', spoc: 'Ashwin Kumar', budget: 500000, committed: 345000, remaining: 155000, utilPct: 69 },
  { id: 'EVT-2026-002', name: 'Product Launch Q3', spoc: 'Priya Menon', budget: 250000, committed: 215000, remaining: 35000, utilPct: 86 },
  { id: 'EVT-2026-003', name: 'Client Appreciation Gala', spoc: 'Rahul Sharma', budget: 1200000, committed: 850000, remaining: 350000, utilPct: 70.8 },
  { id: 'EVT-2026-004', name: 'Sales Kickoff Bangalore', spoc: 'Suresh Babu', budget: 180000, committed: 195000, remaining: -15000, utilPct: 108.3 },
]);

onMounted(async () => {
  try {
    const list = await frappeGetDocList('Event Master', {
      fields: ['name', 'event_name', 'spoc', 'allocated_budget', 'total_committed_spend', 'remaining_budget', 'budget_utilization_pct'],
      limit: 20,
    });
    if (list && list.length) {
      events.value = list.map(r => ({
        id: r.name,
        name: r.event_name || r.name,
        spoc: r.spoc || 'SPOC',
        budget: Number(r.allocated_budget || 0),
        committed: Number(r.total_committed_spend || 0),
        remaining: Number(r.remaining_budget || 0),
        utilPct: Number(r.budget_utilization_pct || 0),
      }));
    }
  } catch (err) {
    console.warn('Fallback to demo events:', err);
  }
});

const totalAllocated = computed(() => events.value.reduce((acc, x) => acc + x.budget, 0));
const totalCommitted = computed(() => events.value.reduce((acc, x) => acc + x.committed, 0));
const overrunCount = computed(() => events.value.filter(x => x.utilPct >= 80).length);
</script>

