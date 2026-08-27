# UI Philosophy: Prompt Workflow First

## Implementation status: 2026-05-31

The current Pro UI implements the documented layer split:

- Navigation Workspace: Prompt Graph, PromptCloud, Search, section links, and return links.
- Editing Layer: Prompt Lines, Batch Editing, Selected Token Actions, and Token Reorder.
- Detail & Execution Workspace: Preview, Metadata, ComfyUI, Generation, and Export.

Graph and PromptCloud should continue to be treated as navigation, exploration, and selection-input tools. General prompt transformations belong in Prompt Lines and Batch Editing. Downstream inspection and execution belong in Detail & Execution.

Global Module Library v1 exists as reusable user-level asset storage. Global modules are copied into project-local module libraries before use; project-local modules remain the active source for insertion, replacement, export, and active prompt expansion. There is no live synchronization between global and project modules.

この文書は、PromptGraph Pro の UI 再編後の基本方針を将来の開発セッション向けに残すための project memory です。

## 基本方針

PromptGraph Pro の人間向け UI は、グラフ編集ツールではなく、AI イラスト制作のための prompt workflow editing tool として設計する。

- Graph / PromptCloud / Search は navigation and exploration layer。
- Prompt Lines / Batch Editing は primary editing layer。
- Preview / Metadata / ComfyUI / Generation / Export は detail and execution layer。
- Graph は構造理解、探索、選択入力のためのビューであり、人間が直接編集する主画面ではない。
- 人間は prompt/image workflow を編集する。
- AI/agent は将来的に graph structure を直接使う可能性があるが、それは人間向け UI とは別の設計軸として扱う。

## Graph と PromptCloud の役割

Graph と PromptCloud は、プロンプト群の構造を理解するための探索レイヤーである。

- どの token が頻出するかを見る。
- prompt line 間の共通 spine や mutation を把握する。
- Focus Edit 中に対象 line の token context を確認する。
- Graph/PromptCloud selection は、編集対象 token を選ぶための入力として扱う。

Graph node selection は、独立した「グラフ編集モード」ではない。選択された graph node は、Batch Editing 内の token/prompt 操作に渡される selection input として扱う。

## Editing Layer

Prompt Lines と Batch Editing が編集の中心である。

- Prompt Lines は line selection と line-level editing の起点。
- Batch Editing は rename / remove / weight / reorder / add などの prompt transformation を集約する場所。
- Selected Token Actions は、Graph / PromptCloud から選ばれた token を Batch Editing 内で扱うための UI。
- Token Reorder は旧 Move Nodes を吸収した token ordering 操作。

## 最近の UI 判断

初期の UI 整理で、以下の判断を行った。

- Quick Actions は中央 workspace から削除した。
- Selection Actions は Batch Editing に移動した。
- legacy Quick Actions dead code は削除した。
- Node Operations は削除し、Move Nodes は Token Reorder として Batch Editing に移した。
- Selection Actions は Selected Token Actions に改名した。

この流れは、UI を graph-centric editing から prompt workflow editing へ寄せるための意図的な整理である。

## 今後の判断基準

新しい編集機能を追加するときは、まず Batch Editing / Prompt Lines / Focus Edit のどこに置くべきかを考える。

- 構造を見るだけなら Graph / PromptCloud。
- 複数 prompt line に適用する編集なら Batch Editing。
- 1 行を確認しながら編集するなら Focus Edit。
- 生成、比較、メタデータ確認なら Detail / Execution layer。

Graph に直接編集 UI を増やす場合は、それが本当に graph-specific なのか、単に prompt token editing を別の場所に重複させているだけなのかを確認する。
