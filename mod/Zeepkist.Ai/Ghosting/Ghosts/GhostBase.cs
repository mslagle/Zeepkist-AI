using TNRD.Zeepkist.GTR.Ghosting.Playback;
using UnityEngine;

namespace TNRD.Zeepkist.GTR.Ghosting.Ghosts;

public abstract class GhostBase : IGhost
{
    private int _updateFrame;
    private int _fixedUpdateFrame;

    protected abstract int FrameCount { get; }

    protected GhostData Ghost { get; private set; }

    public abstract Color Color { get; }

    protected GhostBase()
    {
    }

    public void Initialize(GhostData ghost)
    {
        Ghost = ghost;
    }

    public abstract void ApplyCosmetics(string steamName);

    protected void SetupCosmetics(CosmeticsV16 cosmetics, string steamName, ulong steamId)
    {
        Ghost.Visuals.Cosmetics = cosmetics;
        Ghost.Visuals.GhostModel.DoCarSetup(Ghost.Visuals.Cosmetics, true, true, false);
        Ghost.Visuals.GhostModel.SetupParaglider(Ghost.Visuals.Cosmetics.GetParaglider());
        Ghost.Visuals.GhostModel.DisableParaglider();
        Ghost.Visuals.HornHolder.SetActive(false);
        Ghost.Visuals.NameDisplay.kingHat.gameObject.SetActive(false);
        Ghost.Visuals.NameDisplay.DoSetup(steamName, steamId.ToString(), Color);

        if (Ghost.Visuals.Cosmetics.horn != null)
        {
            Ghost.CurrentHornType = Ghost.Visuals.Cosmetics.horn.hornType;
            Ghost.CurrentHornIsOneShot = Ghost.CurrentHornType == FMOD_HornsIndex.HornType.fallback ||
                                         Ghost.Visuals.Cosmetics.horn.currentHornIsOneShot;
            Ghost.CurrentHornTone = Ghost.Visuals.Cosmetics.horn.tone;
        }
        else
        {
            Ghost.CurrentHornType = FMOD_HornsIndex.HornType.fallback;
            Ghost.CurrentHornIsOneShot = true;
            Ghost.CurrentHornTone = 0;
        }
    }

    public void Start()
    {
        _updateFrame = 0;
        _fixedUpdateFrame = 0;

        IFrame frame = GetFrame(0);
        Ghost.GameObject.transform.SetPositionAndRotation(frame.Position, frame.Rotation);
    }

    public void Stop()
    {
        _updateFrame = 0;
        _fixedUpdateFrame = 0;
    }

    protected virtual void OnUpdate()
    {
    }

    public void FixedUpdate()
    {
        if (_fixedUpdateFrame >= FrameCount - 1)
            return;

        OnFixedUpdate(_fixedUpdateFrame);

        _fixedUpdateFrame++;
    }

    protected virtual void OnFixedUpdate(int fixedUpdateFrame)
    {
    }

    protected abstract IFrame GetFrame(int index);

    public void Update()
    {
        throw new System.NotImplementedException();
    }
}
