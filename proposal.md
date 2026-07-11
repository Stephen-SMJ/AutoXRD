Proposal: AutoXRD
Skill-Guided LLM Agents for Automated Powder XRD Analysis and Physically Auditable Rietveld Refinement
1. Motivation

粉末 XRD 是材料结构表征中最常用的技术之一，但从原始谱图到可靠结论之间仍然高度依赖专家经验。原因在于粉末衍射把三维倒易空间投影到一维，导致大量衍射峰重叠；Rietveld 方法虽然通过全谱拟合缓解了“独立反射不足”的问题，但它本质上仍是一个强物理约束、强参数耦合、容易局部最优的非线性最小二乘过程。上传的 Rietveld 课件中也强调：全谱拟合依赖峰形函数、峰宽函数、本底函数、择优取向校正，并且需要在结构参数和峰形参数之间分步精修，而不是一次性释放所有变量 。

FullProf 官方文档也明确指出，FullProf 不是一个自动黑箱程序，用户仍需要具备晶体学、磁学、衍射物理和数据分析背景；同时，手册强调需要可视化 observed/calculated/difference pattern 来判断拟合是否可信。

因此，普通 LLM Agent 很容易失败：它把任务看成“调用软件 + 修改输入文件”，但真正的难点是何时 refine 哪些参数、如何诊断残差、如何识别错误相/择优取向/本底/峰宽/零点漂移、如何避免低 Rwp 但物理错误的结果。

2. Research Goal

本项目目标是提出 AutoXRD：一个面向粉末 XRD 分析和 Rietveld refinement 的 skill-guided LLM Agent。它不直接让 LLM 自由编辑 .pcr 或盲目调用 FullProf，而是把 Rietveld 专家流程拆成一组 typed skills，由 LLM 负责规划和解释，由 FullProf/GSAS-II/BGMN 等后端负责数值 refinement，由 validator 负责物理约束和结果审计。

一句话定位：

AutoXRD turns XRD/Rietveld refinement into a typed, auditable, physics-constrained agent environment.

论文不应声称“第一个自动 Rietveld”或“第一个 LLM Rietveld Agent”。已有 SrRietveld 自动化 GSAS/FullProf，AutoFP 用专家系统控制 FullProf，PowderBot 用 RL 控制 FullProf，BBO-Rietveld 用黑箱优化自动搜索 refinement 配置；2026 年也已经有 Rongzai LLM agent 和 AgentBuild for Rietveld refinement。

AutoXRD 的 novelty 应该放在：

typed skill layer：LLM 不直接写 .pcr，而是调用结构化技能。
residual-driven planning：根据差谱和错误模式决定下一步 refinement。
physical validation：低 Rwp 不直接通过，必须检查晶胞、占有率、B factor、键长键角、参数相关性、相分数等。
multi-hypothesis XRD reasoning：对多相和未知相问题，输出多个候选解释，而不是强行给一个答案。
AutoXRD-Bench：把 XRD refinement 做成一个可复现的 Agent benchmark，评估 trajectory、物理可信度和拟合质量。
3. Core Scientific Insight

Rietveld refinement 的核心不是“曲线拟合”，而是：

θ
min
	​

i
∑
	​

w
i
	​

(Y
i
obs
	​

−Y
i
calc
	​

(θ))
2

其中 θ 同时包含结构参数和实验/峰形参数。课件中把参数分为两类：结构参数，如晶胞参数、原子坐标、占有率、温度因子；峰形参数，如峰形、半宽度、不对称、择优取向、本底等 。FullProf 也支持 XRD/NPD、多相、background、profile functions、preferred orientation、size/strain、Le Bail profile matching、多谱联合 refinement 和 restraints。

所以 AutoXRD 的核心任务是把专家判断自动化：

专家判断	AutoXRD 对应能力
谱图质量是否足够	Pattern QC skill
峰位不对是 zero shift 还是 lattice problem	Residual diagnosis skill
峰强不对是结构、择优取向还是漏相	Intensity diagnosis skill
峰宽不对是仪器、size/strain 还是 profile function	Broadening diagnosis skill
什么时候 refine scale/lattice/background/profile/atomic/occupancy	Refinement planner
Rwp 降低但结构是否可信	Physical validator
多个相组合都能解释谱图怎么办	Multi-hypothesis manager
4. Why General Agents Fail

普通 Agent 不适合直接做 XRD refinement，主要有五个原因。

第一，.pcr 文件结构复杂且脆弱。FullProf 的主控制文件包含衍射条件、相信息、profile 参数、约束、codeword 等，顺序和格式错误会导致运行失败或隐性错误。让 LLM 自由编辑 .pcr 会产生大量 invalid input。

第二，参数强耦合。FullProf manual 明确建议不要一开始 refine 所有结构参数；有些参数强烈影响 residual，需要先 refine，另一些参数只能在后期释放。 普通 Agent 往往缺乏这种 staged refinement 策略。

第三，低 Rwp 不等于正确结构。BBO-Rietveld 也指出，小 Rwp/GOF 并不能保证 refined structure 就是实验数据的合理解释。

第四，多相/未知相存在多解性。Dara 的出发点就是 powder XRD 只提供结构信息，多个 reference phases 可能拟合同一谱图，因此需要 multiple hypotheses。

第五，谱图问题很多来自实验而非模型。上传课件中强调峰位准确度受仪器、光束、吸收、零点校正影响；强度受择优取向和制样方法影响，并举例说明制样方式会显著改变强度，甚至导致结构求解失败 。普通 Agent 如果只优化 Rwp，会把实验伪影误解释成结构变化。

5. AutoXRD System Design
5.1 Overall Architecture
User Request / XRD Pattern / CIF / Composition
        ↓
Task Parser
        ↓
Pattern QC + Peak Analysis
        ↓
Candidate Phase / Structure Retrieval
        ↓
Typed Skill Layer
        ├── PCR generation & validation
        ├── Le Bail / profile matching
        ├── staged Rietveld refinement
        ├── FullProf execution & parsing
        ├── residual diagnosis
        ├── physical validation
        ├── multi-hypothesis search
        └── report generation
        ↓
FullProf / GSAS-II / BGMN / Optuna Backend
        ↓
Auditable Refinement Trajectory + Final Scientific Report

关键原则：

LLM does planning, not numerical fitting. FullProf does refinement. Validators decide whether the trajectory is scientifically acceptable.

6. Skill Design
Skill 1: Pattern QC and Preprocessing

输入 .xy/.dat/.csv/.raw/.ras 等谱图，输出标准化谱图状态：

PatternState = {
    "two_theta": array,
    "intensity": array,
    "sigma": optional_array,
    "wavelength": optional_float,
    "radiation": "CuKa" | "MoKa" | "synchrotron" | unknown,
    "step_size": float,
    "scan_range": [min_2theta, max_2theta],
    "detected_peaks": list,
    "estimated_background": array,
    "noise_level": float,
    "suspected_artifacts": list
}

这个 skill 负责判断：

是否有明显零点偏移；
是否有异常背景；
是否有 amorphous hump；
是否存在严重 peak overlap；
是否存在强烈 preferred orientation；
step size 是否合理。

课件中提到实验目标是获得“高分辨高准确的数字粉末衍射谱”，扫描步宽建议约为最小 FWHM 的 1/4–1/5，最大每步计数可在 5000–10000 左右，这些都可以转成 QC 规则 。

Skill 2: Candidate Phase Retrieval

根据用户给出的 composition、CIF、phase name 或已知材料体系，检索候选结构：

retrieve_phases(
    composition="Li-La-Zr-O",
    databases=["COD", "MaterialsProject", "local_cif"],
    top_k=50
)

输出：

CandidatePhase = {
    "formula": str,
    "space_group": str,
    "lattice": dict,
    "cif_path": str,
    "source": str,
    "chemical_score": float,
    "peak_match_score": float
}

对于未知相和多相体系，AutoXRD 不应该只选一个候选，而应该维护 hypothesis pool。这一点和 CrystalShift、Dara 的思想一致：XRD phase labeling 本质上需要候选组合搜索和概率/多假设输出。

Skill 3: PCR Generation and Validation

不要让 LLM 直接写 FullProf .pcr。应该设计一个中间 DSL：

create_pcr(
    pattern_file,
    phases,
    instrument_config,
    background_model,
    profile_function,
    refinement_flags,
    constraints
)

然后由 validator 检查：

- phase block 数量是否正确
- atom block 是否与 CIF 一致
- codeword 是否冲突
- refined parameter 数量是否过多
- cell / wavelength 是否同时错误释放
- occupancy / Biso 是否有合理 bounds
- background order 是否过高
- preferred orientation 是否有合理方向

这样可以把 .pcr 文件从“LLM 自由文本生成”变成“受控结构化生成”。

Skill 4: Le Bail / Profile Matching Skill

上传课件中专门讲了 Pawley 法和 Le Bail 法：Le Bail 不需要结构模型，只需要晶胞参数和峰形参数，精修参数较少、收敛快、应用广泛，并且 FullProf 支持 Le Bail profile matching 。FullProf 官方页面也明确支持 profile matching / Le Bail fit。

因此 AutoXRD 应该先用 Le Bail 做 profile-level 对齐：

Goal: fit peak positions, background, profile shape before structural refinement.
Refine: zero shift, lattice parameters, background, U/V/W, asymmetry.
Do not refine: atomic positions, occupancy, Biso.

这个阶段可以区分：

峰位整体偏移：zero shift；
峰位随角度偏差：lattice/cell；
峰形不对：profile function；
本底系统性偏差：background model；
有未解释峰：missing phase。
Skill 5: Staged Rietveld Planner

Refinement action space 应该离散化：

Action = Literal[
    "refine_scale",
    "refine_zero",
    "refine_background",
    "refine_lattice",
    "refine_profile_UVW",
    "refine_asymmetry",
    "refine_preferred_orientation",
    "refine_atomic_positions",
    "refine_Biso",
    "refine_occupancy",
    "refine_size_strain",
    "freeze_unstable_parameter",
    "add_phase",
    "remove_phase",
    "exclude_region",
    "switch_profile_function"
]

默认 refinement curriculum：

Stage 0: Pattern QC + metadata check
Stage 1: Le Bail/profile matching
Stage 2: scale + zero + lattice
Stage 3: background + profile U,V,W + asymmetry
Stage 4: atomic positions with constraints
Stage 5: Biso / occupancy, only if stable
Stage 6: preferred orientation / size-strain / microstructure
Stage 7: final physical validation and report

这与课件中的“分步精修 → 整体精修”“引入键长键角约束”“择优取向校正、峰形不对称修正、多组数据同时精修”的策略一致 。

Skill 6: FullProf Execution and Output Parsing

每一步 refinement 都保存完整 trajectory：

run_001/
  input.pcr
  output.out
  result.prf
  refined.pcr
  metrics.json
  action.json
  observed_calculated_difference.png
  warnings.json

Parser 提取：

RefinementResult = {
    "Rp": float,
    "Rwp": float,
    "Rexp": float,
    "GoF": float,
    "parameter_shifts": dict,
    "standard_errors": dict,
    "correlations": dict,
    "warnings": list,
    "failed": bool,
    "physical_violations": list
}
Skill 7: Residual Diagnosis Skill

这是 AutoXRD 最重要的差异化能力。它不只读 Rwp，而是看差谱模式：

Residual pattern	Possible cause	Next action
所有峰整体偏移	zero shift	refine zero
高角峰偏移更明显	lattice/cell problem	refine lattice
峰顶拟合不好	profile function	switch PV/TCH or refine U,V,W
峰左/右不对称	asymmetry / axial divergence	refine asymmetry
某些峰强度系统性错误	preferred orientation / wrong structure	refine PO or check phase
出现未解释峰	missing phase	add candidate phase
宽峰无法解释	size/strain / amorphous	microstructure skill
背景系统性残差	background model	increase or change background model

FullProf manual 强调 observed/calculated/difference plot 对检查模型和输入错误非常重要。

Skill 8: Physical Validator

最终接受条件不能只看 Rwp。Validator 应该检查：

Hard constraints:
- occupancy ∈ [0, 1] or chemically allowed range
- Biso > 0 and not extremely large
- phase fraction ≥ 0
- lattice parameters within plausible deviation
- bond lengths / bond angles chemically reasonable
- no severe parameter divergence
- no singular matrix / invalid covariance

Soft constraints:
- lower Rwp/Rexp
- lower residual peak score
- fewer unexplained peaks
- fewer refined parameters
- lower parameter correlation
- reasonable uncertainty

输出：

ValidationReport = {
    "accepted": bool,
    "fit_quality": float,
    "physical_validity": float,
    "residual_quality": float,
    "complexity_penalty": float,
    "failure_reasons": list
}

一个候选的综合分数可以设计为：

Score(H)=α⋅
R
exp
	​

R
wp
	​

	​

+β⋅V
phys
	​

+γ⋅S
residual
	​

+δ⋅C
complexity
	​

+η⋅U
uncertainty
	​


其中 V
phys
	​

 是物理违规数，S
residual
	​

 是未解释峰/系统残差，C
complexity
	​

 是参数复杂度惩罚。

Skill 9: Multi-Hypothesis Manager

对于未知相或多相样品，AutoXRD 输出多个 hypothesis：

Hypothesis 1: Li7La3Zr2O12 + La2Zr2O7
Hypothesis 2: Li7La3Zr2O12 + La2O3 + ZrO2
Hypothesis 3: La2Zr2O7 dominant phase

每个 hypothesis 给出：

- Rwp / Rexp / GoF
- unexplained peak ratio
- phase fraction
- chemical consistency
- physical validity
- why accepted / rejected

Dara 已经证明 multiple-hypothesis phase identification 是复杂 XRD 自动化中的关键方向。 AutoXRD 可以把这个思想和 LLM trajectory reasoning、FullProf skills、physical validator 结合起来。

7. AutoXRD-Bench: Benchmark Design
Task A: Known-Phase Rietveld Refinement

输入：

XRD pattern + correct CIF + wavelength/instrument metadata

目标：

自动完成 refinement，输出可信结构参数和拟合报告。

数据来源：

FullProf examples/tutorials；
BBO-Rietveld 使用过的材料，如 Y2O3、Dy0.5Sr0.5MnO3、LiCoO2；
RAPID/CNN refinement 论文中使用的 CeO2、Tb2BaCoO5、PbSO4 等 FullProf example / experimental datasets。

指标：

- convergence success rate
- Rwp / Rp / Rexp / GoF
- lattice parameter error
- atomic position error
- physical invalid rate
- number of FullProf calls
- runtime
- invalid PCR rate
Task B: Robustness Under Experimental Artifacts

对已知结构模拟扰动：

- noise increase
- zero shift
- background distortion
- preferred orientation
- peak broadening
- missing weak peaks
- impurity peaks
- limited 2θ range

目标是测试 AutoXRD 是否能诊断“为什么拟合不好”，而不是只降低 Rwp。

指标：

- diagnosis accuracy
- refinement recovery rate
- wrong-fix rate
- physical violation rate
- Rwp degradation under noise
Task C: Unknown / Multiphase Phase Identification

输入：

XRD pattern + optional composition

输出：

top-k phase hypotheses + Rietveld verification

数据来源可以包括 opXRD、SIMPOD、SimXRD-4M、Dara benchmark。opXRD 收集了 92,552 个实验 pXRD diffractograms，其中 2,179 个带标签；SIMPOD 包含 467,861 个 COD-derived crystal structures 及其 simulated PXRD patterns；SimXRD-4M 包含超过 400 万个 simulated XRD patterns。

指标：

- phase top-1 / top-k accuracy
- phase precision / recall / F1
- phase fraction MAE
- unexplained peak ratio
- false confident answer rate
Task D: Quantitative Phase Analysis and Microstructure

上传课件中指出，多相定量分析可以通过全谱拟合得到各相 scale factor S
p
	​

，进一步计算相含量；微结构分析则可通过峰宽函数分离晶粒尺寸和微应变贡献 。因此可以设计 QPA 和 microstructure 子任务。

数据来源：

合成多相 mixtures；
NIST SRM 676a / fly ash SRM 等用于 QPA 的标准材料或文献数据。NIST SRM 676a 是用于 powder diffraction QPA 的 corundum internal standard。

指标：

- phase weight fraction MAE
- amorphous content error
- crystallite size error
- microstrain error
- uncertainty calibration
8. Baselines
Refinement Baselines
Baseline	Description
FullProf default	单次模板 refinement
Refine-all	一开始释放所有参数
Rule-based sequence	手写专家顺序
AutoFP-style expert system	模拟 AutoFP 思路
BBO / Optuna-Rietveld	黑箱搜索 refinement configuration
LLM direct-edit PCR	让 LLM 直接改 .pcr
AutoXRD	skill-guided + validator + residual diagnosis
Phase Identification Baselines
Baseline	Description
Search-match	传统 peak matching
CrystalShift	probabilistic phase labeling
Dara	multi-hypothesis Rietveld phase ID
XCA	AI companion agent for XRD phase identification
RADAR-PD	mismatch-tolerant multiphase identification + Rietveld verification
AutoXRD	LLM skill-based multi-hypothesis refinement

XCA、CrystalShift、Dara、RADAR-PD 都说明自动 XRD phase identification 是一个活跃方向；AutoXRD 的差异应体现在“trajectory-level agent + FullProf typed skills + physical validators + benchmark”，而不是单纯 phase classifier。

9. Main Experiments
Experiment 1: Does skill-guided refinement outperform naive LLM agents?

比较：

LLM direct-edit PCR
LLM tool-use without validator
Rule-based sequence
AutoXRD

看：

Rwp, success rate, invalid PCR rate, physical violation rate, FullProf calls

预期结果：

AutoXRD 不一定总是最低 Rwp，但应该显著降低 invalid trajectory 和 unphysical refinement。

Experiment 2: Does residual diagnosis improve robustness?

在 known-phase benchmark 上加入 zero shift、background distortion、preferred orientation、extra peaks。

比较：

AutoXRD without residual diagnosis
AutoXRD full

看：

diagnosis accuracy, recovery rate, final physical validity
Experiment 3: Does physical validation catch low-Rwp wrong solutions?

构造 candidate phase ambiguity：多个相都能得到相近 Rwp。

比较：

Rwp-only selection
AutoXRD multi-objective selection
Human/expert reference

看：

wrong phase accept rate
false confidence rate
top-k hypothesis quality
Experiment 4: Multiphase phase identification

在 opXRD / Dara benchmark / synthetic mixtures 上比较：

Search-match
CrystalShift
Dara
AutoXRD

看：

phase recall, phase precision, top-k accuracy, unexplained peak ratio, phase fraction MAE
Experiment 5: Ablation Study
Variant	Removed component
AutoXRD-full	none
w/o PCR validator	允许 LLM 直接生成/修改 .pcr
w/o residual diagnosis	只根据 Rwp 决策
w/o physical validator	只看 fit metrics
w/o Le Bail stage	直接 Rietveld
w/o multi-hypothesis	只保留 top-1 phase

核心预期：

w/o PCR validator → invalid input 增加
w/o residual diagnosis → 收敛慢且 wrong fix 增加
w/o physical validator → low-Rwp but wrong/unphysical solutions 增加
w/o Le Bail → 初始不稳，失败率上升
w/o multi-hypothesis → phase ambiguity 处理变差
10. Expected Contributions
Contribution 1: AutoXRD Agent Architecture

提出一个面向 XRD/Rietveld 的 typed skill agent framework，把专家操作变成可调用、可验证、可审计的技能。

Contribution 2: Residual-Driven Refinement Policy

提出基于 observed/calculated/difference pattern 的 action selection，把差谱模式映射到 refinement 动作。

Contribution 3: Physics-Aware Validation

提出不仅依赖 Rwp/GoF 的多目标评价，包括物理合理性、参数稳定性、残差解释性、相组合可信度。

Contribution 4: AutoXRD-Bench

构建一个包含 known-phase refinement、artifact robustness、multiphase identification、QPA/microstructure 的 benchmark，用于评估 XRD agents。

Contribution 5: Trajectory-Level Evaluation

不仅评估最终结果，还评估 refinement trajectory：动作是否合理、是否过早释放参数、是否产生 invalid PCR、是否低 Rwp 但物理错误。

11. Implementation Plan
Phase 1: MVP Known-Phase Auto Refinement

目标：跑通 20–50 个 known-phase tasks。

实现：

- pattern reader
- CIF parser
- PCR generator
- FullProf runner
- output parser
- staged planner
- physical validator
- report generator

只做：

pattern + CIF → refined structure/report

不做：

unknown phase identification
ab initio structure solution
complex magnetic refinement

这是最小可发版的核心。

Phase 2: Robustness Benchmark

加入模拟扰动：

noise, zero shift, background, preferred orientation, peak broadening, impurity peaks

测试 AutoXRD 是否能诊断和修复。

Phase 3: Multiphase and Candidate Search

加入：

COD/Materials Project retrieval
peak matching
multi-hypothesis manager
phase fraction refinement

对比 Dara / CrystalShift / search-match。

Phase 4: Paper-Ready Benchmark and Ablation

整理：

- AutoXRD-Bench
- baselines
- ablation
- case studies
- trajectory visualizations
- failure analysis
12. Paper Positioning

推荐题目：

AutoXRD: Skill-Guided LLM Agents for Physically Auditable Powder X-ray Diffraction Refinement

或者更 benchmark-oriented：

AutoXRD-Bench: Evaluating LLM Agents for Automated XRD Analysis and Rietveld Refinement

摘要主线可以这样写：

Powder XRD analysis remains a bottleneck in high-throughput materials discovery because Rietveld refinement requires expert-driven staged parameter control, residual interpretation, and physical validation. Existing automation methods rely on scripts, expert systems, black-box optimization, reinforcement learning, or phase-search pipelines. We introduce AutoXRD, a skill-guided LLM agent that performs automated XRD analysis through typed refinement actions, deterministic crystallographic engines, residual-driven planning, and physics-aware validation. AutoXRD generates auditable refinement trajectories and multi-hypothesis reports rather than only optimizing Rwp. We further introduce AutoXRD-Bench, covering known-phase refinement, experimental artifact robustness, multiphase identification, and quantitative phase analysis.

13. Risk and Mitigation

最大风险是已有工作很多，尤其是 AutoFP、BBO-Rietveld、Dara、Rongzai、AgentBuild。所以论文不能写成“我们第一次自动化 Rietveld”。应写成：

Existing methods automate refinement engines or phase search,
but they do not systematically evaluate LLM agents as physically constrained,
trajectory-level XRD refinement systems.

第二个风险是 FullProf .pcr 复杂，工程实现会很慢。解决方案是第一版只支持：

single-pattern
single-phase / two-phase
non-magnetic
constant-wavelength XRD
known CIF
limited profile functions: PV/TCH-PV

第三个风险是 benchmark ground truth 不够。解决方案是先用 simulated/controlled benchmark，再用 opXRD/Dara/FullProf examples 做 experimental validation。

14. 最推荐的最小论文版本

我建议先做这个版本：

AutoXRD-MVP: Known-phase Rietveld refinement with skill-guided FullProf planning.

范围：

Input: XRD pattern + CIF + wavelength
Output: refined PCR + metrics + plot + report
Tasks: 50 known-phase refinements + 200 corrupted variants
Baselines: refine-all, rule-based, BBO/Optuna, LLM direct-edit, AutoXRD
Metrics: Rwp, success, invalid PCR, physical violation, calls, runtime

这个版本最容易落地，也最能证明 Agent 的必要性。

真正的完整 AutoXRD 可以作为后续扩展：

known-phase refinement
→ artifact diagnosis
→ multiphase phase identification
→ QPA
→ microstructure
→ ab initio structure solution
15. 最终判断

这个方向值得做，而且比单纯 data agent 更有 AI4Science 味道。但它必须避免“LLM 套壳 FullProf”。真正能写成论文的点是：

XRD/Rietveld 专家知识 → typed skills
Rwp-only fitting → physics-aware validation
single answer → multi-hypothesis reasoning
final metric → trajectory-level benchmark
manual refinement → auditable autonomous refinement

最强的 story 是：

AutoXRD shows that scientific agents should not directly operate brittle scientific software through free-form text. Instead, they should act through typed, validated, physics-aware skills that preserve expert refinement logic and make every scientific decision auditable.
