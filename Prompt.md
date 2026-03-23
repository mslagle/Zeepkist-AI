The training we have done so far does not seem to be working.  Due to this, lets restart from the beginning.  We are looking to create an AI for zeepkist that is able to complete most tracks.  Zeepkist has the following inputs:
1. Up arrow - raises your hands - useful for flying higher when jumping and righting the cart when upside down or sideways
2. Down arrow - brakes your car.  Most tracks will not need this as most tracks are designed not be braked on.  Will also stop all rotation while in the air.
3. Left/Right arrow - turns your car both on a surface and in the air
There is no input for gas.  The game is entirely gravity based.  There are boosters in the game that can accelerate your car though.

To get fast times at zeepkist, you should do the following:
1. Conserve your speed as much as possible by doing the following:
a. Do not oversteer, less inputs means slowing down your car less
b. Avoid airtime as much as possible, hard landings cause your cart to lose speed
c. Use banked corners and road sides to avoid steering
d. Avoid braking as much as possible

Please research the best possible way to create a model that can handle most track types in the game.  I would like the training script to be broken up into the following:
1. A training python script to train the model
2. A c# mod using bepinex to feed the python script with all needed variables to properly train the model (rotation, speed, velocity, location, etc)
We have already created this framework, please modify as needed.

While most tracks in the game do use road pieces, not all road pieces are drivable.  Some may be used for decoration or fake roads.  Also, some tracks may put obstacles in the way in the roads such as cactuses, cats, balls, rocks, etc that will break your car or wheels.

You must also get all checkpoints before arriving at the finish.

Before starting any changes or work, please review your suggestions with me before starting.  Please ask any needed questions.





We will beging training on EZ01.  A few more things to consider:
1. The ghost data does contain current rotation, speed, arms up, brake status at each datapoint.
2. Not all roads are flat, some roads can rotate up to 90 degrees or even have loops
3. Some jumps cannot be landed flat, you may need to land 90 degrees to gravity.  it does not always make sense to always be upwards