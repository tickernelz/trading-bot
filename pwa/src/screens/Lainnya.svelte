<script lang="ts">
  import { GROUPS, inGroup } from "../lib/route.svelte";

  const ABOUT: Record<string, string> = {
    ringkas: "Aman, ditahan, atau berhenti; posisi dan meter rugi",
    grafik: "Kandel per pair dan kurva ekuitas",
    aksi: "Feed order, swarm, risiko, dan sistem",
    swarm: "Jawaban voter per keputusan dan hasil sesudahnya",
    kontrol: "Jeda, lanjut, exit paksa, kunci pair, blacklist",
    konfigurasi: "Batas risiko, swarm, voter, dan catatan perubahan",
    provider: "Status, aktif atau nonaktif, uji koneksi",
    riwayat: "Trade ditutup dan statistik per periode, tag, alasan exit",
    ab: "Kurva ekuitas Bot A dan Bot B bertumpuk",
    audit: "Siapa mengubah apa, kapan, dan hasilnya",
    sistem: "Kesehatan bot, gateway, provider, log, notifikasi",
  };
</script>

{#each GROUPS as group (group)}
  <h2 class="sec">{group}</h2>
  <ul class="links">
    {#each inGroup(group) as s (s.id)}
      <li>
        <a href={"#" + s.id}>
          <span class="name">{s.label}</span>
          <span class="about">{ABOUT[s.id]}</span>
        </a>
      </li>
    {/each}
  </ul>
{/each}

<style>
  .links {
    margin: 0;
    padding: 0 0 var(--space-2);
    list-style: none;
  }
  a {
    display: grid;
    gap: 2px;
    min-height: 56px;
    padding: var(--space-2) var(--space-4);
    text-decoration: none;
    transition: background-color var(--t) var(--ease);
  }
  li + li a {
    border-top: 1px solid var(--rule);
  }
  a:hover,
  a:active {
    background: var(--panel);
  }
  .name {
    font-weight: 600;
  }
  .about {
    font-size: var(--step--1);
    color: var(--ink2);
  }
  h2:first-child {
    border-top: 0;
  }
</style>
