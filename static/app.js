// 入力補助: 新しい作業ログの開始時刻を「現在時刻」にしやすくする。
// 自動保存は意図しない記録を避けるため行わない。
document.addEventListener('DOMContentLoaded', () => {
  const pageDate = document.querySelector('[data-work-date]')?.dataset.workDate;
  const checkDate = () => {
    const today = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Tokyo'}).format(new Date());
    if (pageDate && today !== pageDate) location.reload();
  };
  setInterval(checkDate, 15000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) checkDate();
  });
  document.querySelectorAll('.session-form').forEach((form) => {
    const start = form.querySelector('input[name="start_time"]');
    if (start && !start.value) {
      start.value = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
      }).format(new Date());
    }
  });
});
