# Manager推論環境：ホスト適合性調査

- 調査日：2026-10-22（日本時間）
- 対象：development-management、`codex/mgr-1-manager-overview`
- 基準HEAD：`a03ae10de7f60a611d4180067de72c7c0381ed4b`
- 基準設計：[Manager推論の隔離設計](manager-inference-isolation-design.md)
- 変更範囲：本Markdown文書だけ。コード・OS・認証・実行環境は変更しない。

## 1. 判定

**BLOCKED — 現在のPC／OSのままでは、基準設計で推奨したHyper-V上の専用Linux VM＋Broker方式の検証に進めない。**

CPUの仮想化要件は取得できた範囲で満たすが、OSは **Windows 11 Home**。MicrosoftのHyper-V roleはHomeへインストールできない。単に未有効化のfeatureをONにすればよい状態とは区別する。Pro等への正規のエディション変更、または別の適合ホストの確保が前提になる。[MicrosoftのHyper-V要件](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/Install-Hyper-V)

また、約8GBのRAMに対し調査時の空き物理メモリは約0.86GiBだった。VM用メモリの余裕も確認できていない。これは一時点の値であり、恒久的な容量不足の証明でも、他の作業を停止してよい根拠でもない。

この判定は、Linux VMが原理的に一切使えないという意味ではない。別hypervisorや別PCを使う案の適合性は未調査であり、勝手に方式変更・インストールして迂回しない。隔離の安全性・認証継続・実推論についても未実証のため、`PROVIDER_POLICY_UNVERIFIED` を維持する。

## 2. PCの読み取り確認結果

### 2.1 OS・CPU・メモリ・ストレージ

| 確認項目 | 取得値 | 評価・限界 |
|---|---|---|
| Windows | Microsoft Windows 11 Home | 推奨Hyper-V roleの前提を満たさない |
| Version／Build | 10.0.26200／26200 | Windows 11の返却値。完全な更新revision（UBR）は未取得 |
| Architecture | 64-bit | x64ホスト |
| CPU | Intel Core i7-10510U @ 1.80GHz | CIMの名称。現時点の動作周波数を意味しない |
| Core／Logical processor | 4／8 | 最初のcanary VMの2 vCPUは検討可能な候補 |
| VMMonitorModeExtensions | true | CPUのVM monitor支援ありと報告 |
| SecondLevelAddressTranslationExtensions | true | SLATありと報告 |
| VirtualizationFirmwareEnabled | true | firmware上で仮想化有効とOSから報告。BIOS/UEFI画面は開いていない |
| HypervisorPresent | false | 現在のOSからhypervisorは検出されなかった |
| TotalPhysicalMemory | 8,307,326,976 bytes（約7.74GiB） | 公称8GB相当。増設可否は未調査 |
| TotalVisibleMemorySize | 8,112,624 KiB（約7.74GiB） | OSが見える物理メモリ |
| FreePhysicalMemory | 899,496 KiB（約0.86GiB） | 調査時点の空き。VMを動かせる余裕とは判断しない |
| C: 容量／空き | 507,673,309,184／292,885,516,288 bytes | 空き約272.77GiB。VM予約・backup等を含む運用容量は別に決める |

情報源は `Win32_OperatingSystem`、`Win32_ComputerSystem`、`Win32_Processor`、`Win32_LogicalDisk`。host名、serial、IP、ユーザー名、認証値は記録していない。数値は調査時のsnapshotで、性能測定ではない。

### 2.2 Windows feature・既存環境

| 対象 | 読取結果 | 解釈 |
|---|---|---|
| VirtualMachinePlatform | InstallState=2 | Disabled |
| HypervisorPlatform | InstallState=2 | Disabled |
| Microsoft-Windows-Subsystem-Linux | InstallState=2 | Disabled |
| Hyper-V／Windows Sandbox相当 | 抽出したoptional feature一覧に該当行なし | Homeでの非提供と整合するが、一覧なしだけで全package状態を断定しない |
| Hyper-V PowerShell module | 見つからず | `Get-VM` などは実行していない |
| vmms／vmcompute／LxssManager／WslService | 指定名の取得行0件 | 起動・停止はしていない。別実装・別名や将来状態までは保証しない |
| vmwp／vmmem／vmmemWSL／VirtualBoxVM／vmware-vmx | 指定名のprocess取得行0件 | 調査時に該当processが見つからない範囲の確認 |
| 現在ユーザーのWSL登録 | HKCUのLxssキーなし | 他ユーザーのWSLや、未登録のdisk imageは調査していない |
| VBoxManage／vmrun | PATH上に見つからず | install先を網羅した確認ではない |
| VMware／VirtualBox／Docker Desktop | HKLMの64bit／32bitアンインストール登録の対象表示名0件 | per-user、portable、登録なしの製品・停止中VMの不存在は証明しない |

`Win32_OptionalFeature.InstallState` の1／2／3／4はEnabled／Disabled／Absent／Unknownである。今回は2を「feature未提供」と読み替えていない。[Win32_OptionalFeature](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-optionalfeature)

既存環境との競合は、今回見える範囲で明確な稼働VMを検出しなかった、という評価にとどめる。将来のHyper-V有効化や再起動が、他hypervisor、WSL、VBS、周辺ソフト、WF-6に影響しないという保証はない。広範なVMファイル探索や他ユーザーの環境調査は行っていない。

### 2.3 調査方法と実行しなかった操作

以下の読み取りを、昇格なしで実施した。結果は上の表の必要な属性だけに限定した。

```powershell
Get-CimInstance Win32_OperatingSystem
Get-CimInstance Win32_ComputerSystem
Get-CimInstance Win32_Processor
Get-CimInstance Win32_OptionalFeature
Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
Get-Service -Name vmms,vmcompute,LxssManager,WslService -ErrorAction SilentlyContinue
Get-Process -Name vmwp,vmmem,vmmemWSL,VirtualBoxVM,vmware-vmx -ErrorAction SilentlyContinue
Get-Module -ListAvailable -Name Hyper-V
Get-Command VBoxManage,vmrun -ErrorAction SilentlyContinue
```

追加でHKCUのWSL登録キーの有無と、HKLMの製品登録の表示名・versionだけを確認した。`Win32_Product` は使っていない。

管理者権限が必要となり得るDISM／featureの詳細検査、boot configuration、Hyper-Vの完全なVM一覧、firmware画面での確認は未実施。`wsl`、VM、Sandboxの起動やshutdown、feature enable、firewall、ユーザー作成、認証ファイル、実推論には触れていない。追加権限や再起動を要求する確認を自動で補完していない。

## 3. Codex CLI 0.155.1の静的設定監査

### 3.1 根拠と範囲

ローカル `codex.cmd --version` は `codex-cli 0.155.1`。`codex.cmd features list` は終了コード0だった。`manager_agent.py` の `_command()` はASTとして読み、Providerや推論は起動していない。

比較対象は[公式リポジトリのrust-v0.155.1設定schema](https://raw.githubusercontent.com/openai/codex/rust-v0.155.1/codex-rs/core/config.schema.json)。今回取得したschemaのSHA-256：

`786fee5181619dc73963f7544fa6afe8364236392d999df92d3dd6b3a8c8ac70`

このhashは取得資料の再現確認用であり、インストール済みCLI実行物の真正性を証明する値ではない。schemaのキー・型と、ローカルのfeature stageを照合した。CLIの実効tool一覧・dispatch・OSでの拒否は今回確認していない。

### 3.2 現行15設定との照合

| 生成設定・値 | 同版schema | ローカルfeature stage（取得対象のみ） | 判定 |
|---|---|---|---|
| `approval_policy='never'` | 該当enumあり | 対象外 | 形式整合。全操作禁止の意味ではない |
| `web_search='disabled'` | 該当enumあり | 対象外 | 形式整合。MCPやCLI本体の通信の全禁止ではない |
| `features.shell_tool=false` | boolean | stable | 形式整合。実効性は別検証 |
| `features.unified_exec=false` | boolean | stable | 同上 |
| `features.code_mode=false` | booleanまたはtable | under development | falseは型として許可。将来の版変更監査が必要 |
| `features.multi_agent=false` | boolean | stable | 形式整合 |
| `features.multi_agent_v2=false` | booleanまたはtable | stable | falseは型として許可 |
| `agents.enabled=false` | boolean | 対象外 | 形式整合。multi_agent_v2との優先規則も別に確認 |
| `features.apps=false` | boolean | stable | 形式整合 |
| `features.plugins=false` | boolean | stable | 形式整合 |
| `features.memories=false` | boolean | stable | 形式整合 |
| `features.skill_mcp_dependency_install=false` | boolean | stable | 形式整合。すべてのskill discovery禁止とは同一視しない |
| **`tools.view_image=false`** | **ToolsTomlに該当キーなし** | 対象外 | **設定path不一致。修正候補** |
| `project_doc_max_bytes=0` | integer | 対象外 | 型整合。全設定層や認証領域の非読取保証ではない |
| `mcp_servers={}` | object | 対象外 | 型整合。別layerのserverが必ず消えるとは断定しない |

キーの存在は14/15項目で確認。`features.code_mode` と `features.multi_agent_v2` はbooleanも受け付けるため、table専用だからfalseが無効という判断はしない。

通常の `features list` はManager用の15個のoverrideを適用した実行ではない。同コマンドでshell_tool等がtrueでも、「Managerのfalseが効いていない」とは判定しない。逆に、schemaにfalseが書けることを、禁止したtoolが実行時に消える証拠にも使わない。

### 3.3 修正候補・removed設定

- 同版schemaには **`features.view_image`（boolean）** があり、ローカル一覧ではstable。`tools.view_image=false` からの置換を次のコード修正候補とする。今回は変更しない。
- `features.apply_patch_freeform` と `features.js_repl` はローカルでremoved。schemaには互換用のbooleanが残る。現行MGR-6-fixの生成引数には両方とも含まれていない。「キーがあるから権限制限が成立する」とは扱わず、復活させない。
- 現行CLIには `--ignore-user-config`、`--ignore-rules`、`--skip-git-repo-check`、`--strict-config` の指定がある。前調査の0.155.1 `exec --help` に存在したが、help成功は設定初期化・認証・tool抑制の成功ではない。
- `tools.view_image` はstrict設定での不整合要因として有力だが、元の `PROVIDER_PROTOCOL` の直接原因を実機再現したわけではない。別の設定・プロセス・JSONL異常も未排除。
- Provider既定の `PROVIDER_POLICY_UNVERIFIED` は維持する。設定path修正だけで解除しない。未知設定を無視する、strictを外す、read-onlyを緩める等の起動成功優先は採用しない。

## 4. VM方式の実装可能性

| 層 | 判定 | 根拠／次の条件 |
|---|---|---|
| CPU・firmware支援 | 取得範囲で適合 | VM monitor、SLAT、firmware有効がtrue |
| 現在のWindows上のHyper-V role | **BLOCKED** | Home。正規の対応editionまたは別適合ホストが必要 |
| 調査時のメモリ余裕 | 未確保 | 空き0.86GiB。既存作業を維持できる予算の再測定が必要 |
| diskの見かけの空き | 初期検討には余裕あり | 約272.77GiB。暗号化・backup・予約は未確認 |
| 既存環境との無競合 | UNKNOWN | 対象process等は未検出だが、管理・driver・全VMの網羅確認はしていない |
| CLI制限・Broker・guest認証 | UNKNOWN | 設計段階。OSでの拒否、通信、認証継続は未実証 |
| 全体（現在の推奨案） | **BLOCKED** | 必須のOS条件が欠ける。安全性成立の判定ではない |

現在このPC上で「導入・検証を開始できる」と確認済みの構成はない。CPU対応を根拠にFEASIBLEとはしない。条件解消後の候補は、基準設計と同じ完全Linux VM＋Brokerであり、WSL2単体や空cwdへ安全要件を落として迂回しない。

Home上で使える別hypervisorや別の物理ホストは、追加の調査候補である。製品の導入、ライセンス・更新、hostとの共有境界、guest通信を確認するまで採用済みとは扱わない。今回はVM基盤を新たに選び直していない。

## 5. 最初の実証に絞った最小構成

以下は**前提条件の解消後に検証する案**で、今回作成・起動したものではない。安全要件は基準設計を維持する。

### 5.1 リソースと実行主体

- guest OS候補：Ubuntu Server 24.04 LTS minimal（amd64）、GUIなし。長期保守を優先した検証候補であり、native Codex 0.155.1・認証store・MACとの互換性は最初の準備タスクで確認する。未検証のOS名だけで成立を宣言しない。[Ubuntuのrelease cycle](https://ubuntu.com/about/release-cycle)
- 初回の**非推論canary試験**：2 vCPU、RAM 2GiB、仮想disk 20GiBを仮予算とする。CLI推論には4GiB程度も検討するが、これは実測・ベンダー保証ではない。guestへの割当とは別にhostの既存作業用の余裕を確保する。
- このPCの調査時の空きでは仮予算すら満たさない。メモリを増設できるか、どの時間帯に余裕を確保できるかは人間が確認し、WF-6や他アプリを勝手に止めない。
- 共有folder、host drive、clipboard、USB／device転送、Docker socket、hostの認証cacheはguestへ公開しない。
- guestの管理用supervisorと、推論用の非特権workerを分離。native CLI、runtime、最小設定、必要なguest専用認証領域だけをworkerの許可対象にする。

### 5.2 通信と認証

hostのDCCからは限定ACL付き名前付きpipeでBrokerへ接続し、Brokerからguestへは専用のpeer識別付きチャネルを使う。Hyper-V socketを第一検証候補とするが、Linux guestの対応・認証・停止伝播は未実装。汎用shell RPCや共有folderへのcommand書込で代用しない。

guest内で同じ既存ChatGPTアカウントへ独立ログインする案を維持する。hostのtokenをコピーせず、guestへAPIキーを設定しない。device認証の可否、workspace policy、cache保存・refreshは人間が確認する。今回、認証状態や認証ファイルは読んでいない。hostの同じsessionそのものを再利用できるとは保証しない。

宛先は推測で固定せず、まず偽CLI／ローカル試験serverだけで、直接IP・IPv6・UDP・LAN・host loopback・proxy回避の拒否を実証する。実Codex通信先の確定は別の人間承認済み工程とし、公式案内、対象版実装、秘匿化した接続先メタデータで確認する。HTTP本文・Authorization・tokenを収集しない。必要な認証／推論／refresh宛先が揃うまで広い443許可へfallbackしない。今回この通信試験や認証通信も実行していない。

### 5.3 アクセス拒否と最小Broker

1. 固定image・CLI hash・OS policyを管理側で用意する。modelへ露出するtool一覧0を検証し、shell、画像／file read、MCP、plugin、apps、browser、Code Mode等のdispatchを拒否する。
2. guest側MAC／namespace／exec制限で、native CLIの初期起動と、その後の追加shell・interpreter・別CLI・MCP子process起動を区別する。単なるプロンプト禁止、read-only、専用ユーザーだけで合格にしない。
3. workerにはpolicy・image・業務canaryの変更権限を与えない。CLIの正当な認証更新・最小cache書込と、modelによる編集禁止を両立できるかを確認する。この両立は未解決。
4. Brokerはまず固定の `probe`、`submit`、`cancel`、`status` 相当の小さなプロトコルだけを持つ。最初はsubmit先を偽CLIにし、実Codex推論を使わず安全性を試験する。
5. image／policy／実効toolの検査、VM・job・nonceに結び付く単回lease、byte/frame出力制限、強制deadline、guest job全体の停止、複数DCC process間の排他を最小必須機能とする。
6. 現在の `isolation_check` にTrueを返すだけでは、その後のhost側 `run_streaming()` はguestへ移らない。Manager専用transportもBrokerへ委任し、検証した実行handleでしか推論できないようにする。既存Orchestrator Providerは変更しない。
7. 業務入力はMGR-4の `manager_input` のみ。返すのは固定JSONと確認済み数値・固定failureだけ。path、argv、Provider、隔離設定をAI応答から選べる入口は作らない。
8. MGR-3のJSON検証とMGR-4の正本再収集をhostに残す。既定5分、一度限り、新collectによる無効化、timeout・stopを維持し、TASKへの適用・開始は実装しない。

### 5.4 実装・実証の順序

| 順序 | 実証する内容 | 進めない条件 |
|---|---|---|
| 0 | Homeの制約を解消できるhost案、メモリ予算、保守時間を人間が確定 | 現在はここでBLOCKED |
| 1 | 0.155.1設定path・型の修正候補と、実効tool抑制を非推論で確認 | unknown／removedを安全保証として扱う、禁止toolが残る |
| 2 | 未認証guest、共有なし、合成canaryでread／write／exec拒否 | host到達、guestの権限拡大や追加execができる |
| 3 | 偽CLIでBrokerのlease・排他・期限・出力洪水・停止を試験 | job残存、二重起動、hostへのfallbackが起きる |
| 4 | 人間がguest認証と通信先の限定を別途確認 | host token共有、APIキー、広いnetwork許可が必要になる |
| 5 | 全ゲート後に別途許可された最小実CLI推論 | 実証不足なら `PROVIDER_POLICY_UNVERIFIED` 維持 |

## 6. 未確認事項

- Windowsの完全な更新revision、管理ポリシー、boot／VBS状態、firmware画面での再確認。
- メモリの増設可否、長時間の空き容量・負荷、他作業を維持したVM予算。
- 他ユーザー／portable環境／停止中VMを含む完全なVM inventory、driverレベルの競合。
- 対応editionへの変更可否・費用・再起動計画、または別適合ホストの利用可否。
- 候補guestでの互換性、native CLIの配布物・hash・依存runtime、実効tool一覧とdispatch。
- guest側read／exec禁止と認証refreshの両立、認証・workspaceでの利用可否、最小通信先。
- Brokerの専用通信、単回lease、TOCTOU防止、停止伝播と複数process排他。

これらを管理者権限・新規導入・起動・認証操作で埋め合わせていない。PC条件を将来FEASIBLEに更新できても、隔離完成や実推論の承認とは別の判定とする。

## 7. 想定追加費用と人間の操作

OpenAI API・従量課金API・APIキーは導入しない。将来のCodex推論は既存ChatGPTアカウントの利用枠を使い、quota不足時に自動課金や連続retryへ切り替えない。今回は推論を実行していない。

推奨Hyper-V案をこのPCで続けるなら、対応Windows editionへの正規変更に費用が生じ得る。金額・既存license権利は未調査。RAMの増設や別ホストを選ぶ場合は機材費、VM・Broker・OS・CLIの更新には保守費用がかかる。現在の条件で「追加費用なし」とは判定しない。

実装へ進む前に、人間が次を決める必要がある。今回は操作や承認依頼を実施していない。

1. 対応editionへの変更、別ホスト、または計画保留のどれを選ぶか。Home上の非公式なHyper-V導入で迂回しない。
2. メモリ・CPU・disk予算と、既存作業・WF-6に影響しない保守時間。feature有効化・driver・再起動を行う担当。
3. VM基盤とguest／Brokerの管理担当、共有禁止・network制限・cache保護の配置方針。
4. guestでの人間によるChatGPT独立ログインの可否。host認証をコピーせずに成立しないなら保留。
5. canary試験・偽CLI試験の計画と、合格後にだけ検討する実推論の個別許可。

## 8. 成果物の確認

今回の成果は、このPCの読取結果と、対象版schemaに基づく設定監査・前提不足の判定である。実装ファイルは変更しない。文書の構造・数値・出典・差分を確認し、VM／OS／認証／実推論のテストは実施していない。実行基盤が成立した証拠や、セキュリティ合格記録として本書を使わない。
