<template>
  <!-- 调解结果摘要：达成/未达成关键值，每条标注来源（继承自受理要素 / 人工录入） -->
  <div class="med-summary">
    <template v-if="result.reached">
      <div class="ms-row"><span class="k">协议本金</span>
        <span class="v">{{ (result.settlement?.principal_agreed || 0).toLocaleString() }} 元（人工录入）</span></div>
      <div class="ms-row"><span class="k">履行方式</span>
        <span class="v">{{ (result.settlement?.pay_method || '—') + '（人工录入）' }}</span></div>
      <div v-for="it in (result.settlement?.installments || [])" :key="it.seq" class="ms-row">
        <span class="k">第 {{ it.seq }} 期</span>
        <span class="v">{{ it.due_date }} 前 · {{ (it.amount || 0).toLocaleString() }} 元（人工录入）</span>
      </div>
      <div class="ms-row"><span class="k">利息</span>
        <span class="v">{{ result.settlement?.interest_waived ? '双方互不主张' : '另行约定' }}（人工录入）</span></div>
      <div class="ms-row"><span class="k">司法确认</span>
        <span class="v">{{ result.judicial_confirmation ? '双方同意申请' : '未申请' }}（人工录入）</span></div>
    </template>
    <div v-else class="ms-row"><span class="k">终结原因</span>
      <span class="v">{{ result.settlement?.termination_reason || '—' }}（人工录入）</span></div>
    <div class="ms-row"><span class="k">继承要素</span>
      <span class="v">{{ (inherited || []).map(i => i.field + '=' + i.value).join('、') || '—' }}（继承自受理要素）</span></div>
  </div>
</template>

<script setup>
defineProps({
  result: { type: Object, required: true },
  inherited: { type: Array, default: () => [] },
})
</script>

<style scoped>
.med-summary { padding: 10px 12px; background: #fafbfd; border: 1px solid #eef1f6; border-radius: 8px; }
.ms-row { display: flex; gap: 12px; padding: 4px 0; font-size: 13px; }
.k { flex: none; width: 74px; color: #8492a6; }
.v { color: #2c3a52; }
</style>
